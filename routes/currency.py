# routes/currency.py
from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from services.config import config
from services.schemas import ExchangeRateItem
from services.runner import BatchRunner
from services.reporting import ensure_reports_dir, write_json, write_failed_csv
from services.daily import finalize_batch_tracking, prune_live_trackers, daily_rollup_collect
from services.tracking import read_live_status_summary, PENDING, DONE, SKIPPED

log = logging.getLogger("sapbot")
if not log.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(threadName)s %(message)s"
    )

router = APIRouter()

@router.post("/currency/exchange-rates/batch")
async def create_exchange_rates(items: List[ExchangeRateItem]) -> Dict[str, Any]:
    cfg = config()
    workers = int(cfg.get("NUM_WORKERS", 6)) or 6

    received_count = len(items)
    batch_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + str(uuid.uuid4())[:8]
    reports_root = ensure_reports_dir(Path(cfg.get("REPORTS_DIR") or "reports"))

    runner = BatchRunner(cfg=cfg, batch_id=batch_id, reports_root=reports_root, workers=workers)
    runner.write_request_summary([it.dict() for it in items[:5]], workers)

    start_ts = time.time()
    result = runner.run_force_all_done(items)
    duration_sec = time.time() - start_ts

    # Persist standard artifacts
    result_path = Path(runner.batch_dir) / "result.json"
    failed_json_path = Path(runner.batch_dir) / "failed.json"
    failed_csv_path = Path(runner.batch_dir) / "failed.csv"

    # "Failures" now means anything not Done (i.e., Pending or errors mapped to Pending)
    failed_rows = [r for r in result.get("results", []) if (r.get("status") or "").strip().lower() not in ("created", "skipped")]
    write_json(result_path, result)
    write_json(failed_json_path, failed_rows)
    write_failed_csv(failed_csv_path, failed_rows)

    # Move trackers to finished/<day>/<batch_id>, prune live, and (optionally) daily rollup
    finalize_batch_tracking(batch_id, runner.track_dir)
    try:
        prune_live_trackers()
    except Exception:
        pass
    try:
        if cfg.get("DAILY_REPORTS_ENABLED"):
            _ = daily_rollup_collect()  # compile daily summary/failed.csv
    except Exception:
        pass

    # Strong guarantee: API is "done" only if live tracker summary shows zero Pending
    try:
        live = read_live_status_summary(track_dir=Path(runner.batch_dir).parent.parent / "live" / batch_id)
        # if we moved it already, read_live_status_summary may not find live dir; in that case, trust result["pending"]
    except Exception:
        live = {"Pending": result.get("pending", 0)}

    out = {
        **result,
        "duration_sec": round(duration_sec, 2),
        "reports": {
            "dir": str(runner.batch_dir),
            "result_json": str(result_path),
            "failed_json": str(failed_json_path),
            "failed_csv": str(failed_csv_path),
        },
        "api_ok": (result.get("pending", 0) == 0),  # hardened: only Done/Skipped left
    }
    return out

@router.post("/currency/exchange-rates/batch/stream")
async def create_exchange_rates_stream(items: List[ExchangeRateItem]):
    cfg = config()
    workers = int(cfg.get("NUM_WORKERS", 6)) or 6

    batch_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + str(uuid.uuid4())[:8]
    reports_root = ensure_reports_dir(Path(cfg.get("REPORTS_DIR") or "reports"))

    runner = BatchRunner(cfg=cfg, batch_id=batch_id, reports_root=reports_root, workers=workers)
    runner.write_request_summary([it.dict() for it in items[:5]], workers)

    HEARTBEAT_SEC = int(cfg.get("STREAM_HEARTBEAT_SEC", 5))

    def _gen():
        for line in runner.stream_events(items, heartbeat_sec=HEARTBEAT_SEC):
            yield line

    return StreamingResponse(_gen(), media_type="application/x-ndjson")
