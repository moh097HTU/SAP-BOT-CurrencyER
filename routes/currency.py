# routes/currency.py
from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, DefaultDict, Optional
from collections import defaultdict

from fastapi import APIRouter, BackgroundTasks, HTTPException, Response

from services.config import config
from services.schemas import ExchangeRateItem
from services.runner import BatchRunner
from services.reporting import ensure_reports_dir, write_json, write_failed_csv
from services.daily import finalize_batch_tracking, prune_live_trackers, daily_rollup_collect
from services.tracking import read_live_status_summary

log = logging.getLogger("sapbot")
if not log.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(threadName)s %(message)s"
    )

router = APIRouter()


# ---------- persist incoming payload(s) by records' day ----------
def _group_payload_by_day(items: List[ExchangeRateItem]) -> Dict[str, List[Dict[str, Any]]]:
    """
    Groups normalized payloads by records' day (YYYY-MM-DD), converting from DD.MM.YYYY.
    """
    by_day: DefaultDict[str, List[Dict[str, Any]]] = defaultdict(list)
    for it in items:
        try:
            # ExchangeRateItem already normalizes ValidFrom to DD.MM.YYYY
            d = datetime.strptime(it.ValidFrom, "%d.%m.%Y").strftime("%Y-%m-%d")
        except Exception:
            # If somehow unparseable, skip persisting this row (but still process)
            continue
        by_day[d].append(it.dict())
    return dict(by_day)


def _persist_day_payloads(by_day: Dict[str, List[Dict[str, Any]]]) -> Dict[str, str]:
    """
    Writes each day's payload to WebService/data/<YYYY-MM-DD>/exchange_rates_payload.json.
    Returns a map of day -> path.
    """
    out_paths: Dict[str, str] = {}
    base = Path("WebService") / "data"
    for day, rows in (by_day or {}).items():
        pdir = base / day
        try:
            pdir.mkdir(parents=True, exist_ok=True)
        except Exception:
            try:
                pdir.mkdir(parents=True, exist_ok=True)
            except Exception:
                continue
        path = pdir / "exchange_rates_payload.json"
        write_json(path, rows)
        out_paths[day] = str(path)
    return out_paths
# -----------------------------------------------------------------


# ---------- background runner ----------
def _run_batch_background(
    cfg: Dict[str, Any],
    batch_id: str,
    reports_root: Path,
    items: List[ExchangeRateItem],
    payload_persist_paths: Dict[str, str],
) -> None:
    """
    Heavy work executed off the request thread.
    - Runs the Selenium batch
    - Persists artifacts (JSON/CSV)
    - Relocates under records' day
    - Appends daily rollup
    - Finalizes trackers and prunes
    """
    try:
        workers = int(cfg.get("NUM_WORKERS", 6)) or 6
        runner = BatchRunner(cfg=cfg, batch_id=batch_id, reports_root=reports_root, workers=workers)
        runner.write_request_summary([it.dict() for it in items[:5]], workers)

        start_ts = time.time()
        result = runner.run_force_all_done(items)
        duration_sec = time.time() - start_ts

        # Persist standard artifacts for synchronous compatibility
        result_path = Path(runner.batch_dir) / "result.json"
        failed_json_path = Path(runner.batch_dir) / "failed.json"
        failed_csv_path = Path(runner.batch_dir) / "failed.csv"

        failed_rows = [r for r in result.get("results", [])
                       if (r.get("status") or "").strip().lower() not in ("created", "skipped")]
        write_json(result_path, result)
        write_json(failed_json_path, failed_rows)
        write_failed_csv(failed_csv_path, failed_rows)

        # Persist/email/relocate via runner helper
        result_out = runner.persist_and_email(result, duration_sec)

        # Move trackers to finished/<day>/<batch_id>, prune live, and (optionally) daily rollup
        try:
            finalize_batch_tracking(batch_id, runner.track_dir)
        except Exception:
            pass
        try:
            prune_live_trackers()
        except Exception:
            pass
        try:
            if cfg.get("DAILY_REPORTS_ENABLED"):
                # If we know records_day, use it; else default to today
                _ = daily_rollup_collect(day=result_out.get("records_day"))
        except Exception:
            pass

        log.info(
            "[batch-end] batch_id=%s created=%s failed=%s skipped=%s dur=%.2fs reports=%s",
            batch_id, result_out.get("created"), result_out.get("failed"),
            result_out.get("skipped"), result_out.get("duration_sec"),
            result_out.get("reports", {}).get("dir"),
        )

    except Exception as e:
        log.exception("[batch-error] batch_id=%s %s: %s", batch_id, type(e).__name__, e)
# -----------------------------------------------------------------


def _find_batch_result_path(batch_id: str, base: Path) -> Optional[Path]:
    """
    Try to locate <reports>/<YYYY-MM-DD?>/<batch_id>/result.json
    The batch may have been relocated under records' day.
    """
    # common cases first
    direct = base / batch_id / "result.json"
    if direct.exists():
        return direct
    # relocated under day
    for p in base.glob("*/*/result.json"):
        try:
            if p.parent.name == batch_id:
                return p
        except Exception:
            continue
    # last resort: deeper search
    for p in base.rglob("result.json"):
        if p.parent.name == batch_id:
            return p
    return None


# -------------------- STATUS & RESULT ENDPOINTS --------------------
@router.get("/currency/exchange-rates/batch/{batch_id}/status")
async def get_batch_status(batch_id: str) -> Dict[str, Any]:
    """
    Single source of truth for client polling.

    States:
      - queued   : request accepted, no live tracker or result yet
      - running  : live tracker present and/or driver working
      - succeeded: result.json exists and pending==0 and failed==0
      - failed   : result.json exists and failed>0 or pending>0 after finish
    """
    base = ensure_reports_dir(Path(config().get("REPORTS_DIR") or "reports"))

    # If result.json exists, derive final state
    path = _find_batch_result_path(batch_id, base)
    if path and path.exists():
        import json
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Could not read result.json: {type(e).__name__}: {e}")

        created = int(data.get("created", 0) or 0)
        failed  = int(data.get("failed", 0) or 0)
        skipped = int(data.get("skipped", 0) or 0)
        pending = int(data.get("pending", 0) or 0)

        status = "succeeded" if pending == 0 and failed == 0 else "failed"
        return {
            "task_id": batch_id,
            "status": status,
            "created": created,
            "failed": failed,
            "skipped": skipped,
            "pending": pending,
            "result_path": str(path),
            "ready": True,
        }

    # Else try live tracker => running
    try:
        live = read_live_status_summary(batch_id=batch_id)
        pending = int(live.get("Pending", 0) or 0)
        return {
            "task_id": batch_id,
            "status": "running",
            "pending": pending,
            "ready": False,
        }
    except Exception:
        # No live yet => queued
        return {
            "task_id": batch_id,
            "status": "queued",
            "ready": False,
        }


@router.get("/currency/exchange-rates/batch/{batch_id}/result")
async def get_batch_result(batch_id: str) -> Dict[str, Any]:
    """
    Returns {"ready": False} until result.json appears.
    When ready, returns the parsed result.json.
    """
    base = ensure_reports_dir(Path(config().get("REPORTS_DIR") or "reports"))
    path = _find_batch_result_path(batch_id, base)
    if not path:
        return {"ready": False, "batch_id": batch_id}
    try:
        import json
        data = json.loads(path.read_text(encoding="utf-8"))
        return {"ready": True, "batch_id": batch_id, "result": data, "path": str(path)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not read result.json: {type(e).__name__}: {e}")


@router.get("/currency/exchange-rates/batch/{batch_id}/live")
async def get_live_summary(batch_id: str) -> Dict[str, Any]:
    """
    Summarize the live tracker (if still present).
    """
    try:
        live = read_live_status_summary(batch_id=batch_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"live_summary_error: {type(e).__name__}: {e}")
    return live
# ------------------------------------------------------------------


@router.post("/currency/exchange-rates/batch", status_code=202)
async def create_exchange_rates(
    items: List[ExchangeRateItem],
    background: BackgroundTasks,
    response: Response
) -> Dict[str, Any]:
    """
    Accepts the batch and returns 202 immediately.
    The actual Selenium work is executed in a background task.
    """
    cfg = config()
    batch_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + str(uuid.uuid4())[:8]
    reports_root = ensure_reports_dir(Path(cfg.get("REPORTS_DIR") or "reports"))

    # Persist the incoming payload(s) grouped by records' day for later comparison/fallback
    try:
        grouped = _group_payload_by_day(items)
        persisted_map = _persist_day_payloads(grouped)
        log.info("[payload-persist] days=%s paths=%s", list(grouped.keys()), list(persisted_map.values()))
    except Exception as e:
        log.warning("[payload-persist] failed: %s: %s", type(e).__name__, e)
        persisted_map = {}

    # Launch background processing
    background.add_task(_run_batch_background, cfg, batch_id, reports_root, items, persisted_map)

    status_url = f"/currency/exchange-rates/batch/{batch_id}/status"
    result_url = f"/currency/exchange-rates/batch/{batch_id}/result"

    # Advertise where to poll
    response.headers["Location"] = status_url

    return {
        "accepted": True,
        "task_id": batch_id,          # <-- add this
        "batch_id": batch_id,
        "received": len(items),
        "payload_persist": {"days": list(persisted_map.keys()), "paths": persisted_map},
        "hint": {
            "status": f"/currency/exchange-rates/tasks/{batch_id}/status",
            "result": f"/currency/exchange-rates/tasks/{batch_id}/result",
            "live_summary": f"/currency/exchange-rates/batch/{batch_id}/live",
        },
    }

@router.get("/currency/exchange-rates/tasks/{batch_id}/status")
async def get_task_status(batch_id: str) -> Dict[str, Any]:
    """
    Client-facing status endpoint.
    Looks for reports/<...>/<batch_id>/result.json or live tracker.
    """
    cfg = config()
    base = ensure_reports_dir(Path(cfg.get("REPORTS_DIR") or "reports"))

    # Try finished result first
    path = _find_batch_result_path(batch_id, base)
    if path and path.exists():
        import json
        data = json.loads(path.read_text(encoding="utf-8")) or {}
        created = int(data.get("created") or 0)
        failed  = int(data.get("failed")  or 0)
        skipped = int(data.get("skipped") or 0)
        pending = int(data.get("pending") or 0)

        # 3-way status
        if pending == 0 and failed == 0:
            status = "succeeded"
        elif pending == 0 and failed > 0:
            status = "partial"
        else:
            status = "failed"  # extremely rare if result is present but still shows pending

        return {
            "task_id": batch_id,
            "status": status,
            "created": created,
            "failed": failed,
            "skipped": skipped,
            "pending": pending,
            "ready": True,
            "result_path": str(path),
        }

    # If not finished, try live summary
    try:
        live = read_live_status_summary(batch_id=batch_id)
        pending = int(live.get("Pending") or 0)
        done    = int(live.get("Done") or 0)
        status  = "running" if pending > 0 else "running"  # still running until result.json exists
        return {
            "task_id": batch_id,
            "status": status,
            "pending": pending,
            "done": done,
            "ready": False,
        }
    except Exception as e:
        # No live tracker yet; assume queued/running
        return {
            "task_id": batch_id,
            "status": "running",
            "ready": False,
            "note": f"live_summary_unavailable: {type(e).__name__}: {e}",
        }

@router.get("/currency/exchange-rates/tasks/{batch_id}/result")
async def get_task_result_alias(batch_id: str):
    # delegate to existing batch/{id}/result
    return await get_batch_result(batch_id)
