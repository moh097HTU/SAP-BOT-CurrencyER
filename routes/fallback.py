# routes/fallback.py
from __future__ import annotations

import uuid
import time
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple

from fastapi import APIRouter, Query, HTTPException

from services.fallback_service import run_collect_missing_range, FALLBACK_TRACK_DIR
from services.schemas import ExchangeRateItem
from services.config import config
from services.runner import BatchRunner
from services.reporting import ensure_reports_dir
from services.daily import finalize_batch_tracking, prune_live_trackers, daily_rollup_collect
from services.tracking import read_live_status_summary

router = APIRouter(prefix="/currency/exchange-rates/fallback")

# -------- logging setup --------
def _ensure_logger() -> logging.Logger:
    log = logging.getLogger("sapbot.fallback")
    if not log.handlers:
        log.setLevel(logging.DEBUG)
        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)
        ch.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] fallback %(message)s"))
        log.addHandler(ch)
        log_dir = Path("WebService") / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        fh = RotatingFileHandler(log_dir / "sapbot.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s %(message)s"))
        log.addHandler(fh)
    return log

log = _ensure_logger()
# --------------------------------


# ---------- Helpers ----------
def _parse_iso(s: str) -> date:
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        raise HTTPException(status_code=422, detail=f"Date must be YYYY-MM-DD, got {s!r}")

def _daterange_inclusive(d0: date, d1: date):
    cur = min(d0, d1)
    end = max(d0, d1)
    while cur <= end:
        yield cur
        cur = cur + timedelta(days=1)

def _key_tuple(r: Dict[str, Any]) -> Tuple[str, str, str, str, str]:
    return (
        (r.get("ExchangeRateType") or "").strip().upper(),
        (r.get("FromCurrency") or "").strip().upper(),
        (r.get("ToCurrency") or "").strip().upper(),
        (r.get("ValidFrom") or "").strip(),
        ("Indirect" if (r.get("Quotation") or "").strip().lower().startswith("ind") else "Direct"),
    )

def _load_fallback_rows_for_day(day_iso: str) -> List[Dict[str, Any]]:
    """
    Read WebService/TrackDrivers/Fallback/<YYYY-MM-DD>.json.
    Returns a list[dict]. If file missing or malformed, returns [].
    """
    path = Path(FALLBACK_TRACK_DIR) / f"{day_iso}.json"
    try:
        if not path.exists():
            log.info("refill: file missing for %s → %s", day_iso, path)
            return []
        import json
        txt = path.read_text(encoding="utf-8")
        data = json.loads(txt) or []
        if not isinstance(data, list):
            log.warning("refill: %s is not a list (type=%s) — skipping", path, type(data).__name__)
            return []
        log.info("refill: loaded %s rows from %s", len(data), path)
        return [r for r in data if isinstance(r, dict)]
    except Exception as e:
        log.error("refill: failed to read %s: %s: %s", path, type(e).__name__, e)
        return []

def _normalize_filter_rows(rows: List[Dict[str, Any]]) -> Tuple[List[ExchangeRateItem], Dict[str, int]]:
    """
    - Drop rows without a numeric ExchangeRate > 0
    - De-duplicate by logical key
    - Normalize via ExchangeRateItem (DD.MM.YYYY, Quotation, 5dp)
    """
    stats = {"input": len(rows), "dropped_no_rate": 0, "dedup_removed": 0, "kept": 0}
    log.debug("refill: normalizing %s row(s)", len(rows))

    filtered: List[Dict[str, Any]] = []
    for r in rows:
        val = r.get("ExchangeRate")
        try:
            if val is None:
                stats["dropped_no_rate"] += 1
                continue
            v = float(str(val).replace(",", ""))
            if v <= 0:
                stats["dropped_no_rate"] += 1
                continue
        except Exception:
            stats["dropped_no_rate"] += 1
            continue
        filtered.append(r)

    seen: set[Tuple[str, str, str, str, str]] = set()
    deduped: List[Dict[str, Any]] = []
    for r in filtered:
        k = _key_tuple(r)
        if k in seen:
            stats["dedup_removed"] += 1
            continue
        seen.add(k)
        deduped.append(r)

    out: List[ExchangeRateItem] = []
    for r in deduped:
        try:
            item = ExchangeRateItem(
                ExchangeRateType=(r.get("ExchangeRateType") or "").strip().upper(),
                FromCurrency=(r.get("FromCurrency") or "").strip().upper(),
                ToCurrency=(r.get("ToCurrency") or "").strip().upper(),
                ValidFrom=(r.get("ValidFrom") or "").strip(),
                Quotation=(r.get("Quotation") or "Direct"),
                ExchangeRate=r.get("ExchangeRate"),
            )
            out.append(item)
        except Exception as e:
            stats["dropped_no_rate"] += 1
            log.debug("refill: row failed pydantic normalization and was dropped: %s: %s", type(e).__name__, e)

    stats["kept"] = len(out)
    log.info("refill: normalize stats: %s", stats)
    return out, stats


# ---------- collect missing via Excel ----------
@router.post("/collect-missing")
async def collect_missing(
    date_from: Optional[str] = Query(default=None),
    date_to: Optional[str] = Query(default=None),
) -> Dict[str, Any]:
    if not date_from or not date_to:
        raise HTTPException(
            status_code=400,
            detail="Provide ?date_from=YYYY-MM-DD&date_to=YYYY-MM-DD",
        )

    df = _parse_iso(date_from)
    dt = _parse_iso(date_to)
    log.info("collect-missing: requested range %s → %s", df, dt)
    res = run_collect_missing_range(df, dt)
    log.info("collect-missing: result summary: %s", {k: res.get(k) for k in ("processed_days","total_missing","errors") if k in res})
    return res


# ---------- refill from WebService/TrackDrivers/Fallback/*.json ----------
@router.post("/refill-missing")
async def refill_missing(
    date_from: Optional[str] = Query(default=None),
    date_to: Optional[str] = Query(default=None),
) -> Dict[str, Any]:
    """
    For each day in [date_from, date_to] (inclusive):
      - Read WebService/TrackDrivers/Fallback/<YYYY-MM-DD>.json
      - Normalize + dedupe + drop rows without positive rate
      - Submit to BatchRunner (one batch per day)
    """
    if not date_from or not date_to:
        raise HTTPException(
            status_code=400,
            detail="Provide ?date_from=YYYY-MM-DD&date_to=YYYY-MM-DD",
        )

    df = _parse_iso(date_from)
    dt = _parse_iso(date_to)
    log.info("refill-missing: range %s → %s", df, dt)

    cfg = config()
    reports_root = ensure_reports_dir(Path(cfg.get("REPORTS_DIR") or "reports"))

    overall = {
        "ok": True,
        "total_days": 0,
        "posted_days": 0,
        "skipped_days": 0,
        "errors": 0,
        "total_rows_sent": 0,
        "per_day": [],
    }

    for d in _daterange_inclusive(df, dt):
        overall["total_days"] += 1
        day_iso = d.strftime("%Y-%m-%d")
        log.info("refill: day %s", day_iso)

        raw_rows = _load_fallback_rows_for_day(day_iso)
        if not raw_rows:
            overall["skipped_days"] += 1
            overall["per_day"].append({
                "date": day_iso,
                "ok": False,
                "why": "fallback_file_missing_or_empty",
                "input_rows": 0,
                "kept_rows": 0,
                "dedup_removed": 0,
                "dropped_no_rate": 0,
                "batch_id": "",
            })
            continue

        items, norm_stats = _normalize_filter_rows(raw_rows)
        if not items:
            overall["skipped_days"] += 1
            overall["per_day"].append({
                "date": day_iso,
                "ok": False,
                "why": "no_valid_rows_after_normalization",
                "input_rows": norm_stats["input"],
                "kept_rows": 0,
                "dedup_removed": norm_stats["dedup_removed"],
                "dropped_no_rate": norm_stats["dropped_no_rate"],
                "batch_id": "",
            })
            continue

        batch_id = f"fallback-refill-{day_iso}-{str(uuid.uuid4())[:8]}"
        log.info("refill: posting %d row(s) for %s (batch_id=%s)", len(items), day_iso, batch_id)

        runner = BatchRunner(cfg=cfg, batch_id=batch_id, reports_root=reports_root, workers=int(cfg.get("NUM_WORKERS", 6)) or 6)
        runner.write_request_summary([it.dict() for it in items[:5]], workers=runner.workers)

        start_ts = time.time()
        try:
            result = runner.run_force_all_done(items)
            duration_sec = time.time() - start_ts
            log.info("refill: batch result created=%s failed=%s skipped=%s pending=%s dur=%.2fs",
                     result.get("created"), result.get("failed"), result.get("skipped"), result.get("pending"), duration_sec)

            # Persist/email/etc.
            result_out = runner.persist_and_email(result, duration_sec)

            try:
                finalize_batch_tracking(batch_id, runner.track_dir)
            except Exception as e:
                log.debug("refill: finalize tracking warn: %s", e)
            try:
                prune_live_trackers()
            except Exception:
                pass
            try:
                if cfg.get("DAILY_REPORTS_ENABLED"):
                    _ = daily_rollup_collect(day=day_iso)
            except Exception:
                pass

            try:
                live = read_live_status_summary(track_dir=Path(runner.batch_dir).parent.parent / "live" / batch_id)
            except Exception:
                live = {"Pending": result.get("pending", 0)}

            kept_rows = norm_stats["kept"]
            overall["posted_days"] += 1
            overall["total_rows_sent"] += kept_rows
            overall["per_day"].append({
                "date": day_iso,
                "ok": True,
                "input_rows": norm_stats["input"],
                "kept_rows": kept_rows,
                "dedup_removed": norm_stats["dedup_removed"],
                "dropped_no_rate": norm_stats["dropped_no_rate"],
                "batch_id": batch_id,
                "duration_sec": round(duration_sec, 2),
                "reports": result_out.get("reports", {}),
                "records_day": result_out.get("records_day"),
                "live_has_pending": bool(live.get("Pending", 0)),
                "created": int(result_out.get("created", 0)),
                "failed": int(result_out.get("failed", 0)),
                "skipped": int(result_out.get("skipped", 0)),
            })

        except Exception as e:
            overall["errors"] += 1
            log.exception("refill: runner error for %s: %s", day_iso, e)
            overall["per_day"].append({
                "date": day_iso,
                "ok": False,
                "why": f"runner_error:{type(e).__name__}:{e}",
                "input_rows": norm_stats["input"],
                "kept_rows": norm_stats["kept"],
                "dedup_removed": norm_stats["dedup_removed"],
                "dropped_no_rate": norm_stats["dropped_no_rate"],
                "batch_id": batch_id,
            })

    overall["ok"] = overall["errors"] == 0
    log.info("refill: summary %s", {k: overall[k] for k in ("total_days","posted_days","skipped_days","errors","total_rows_sent")})
    return overall
