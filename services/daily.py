# services/daily.py
from __future__ import annotations

from pathlib import Path
from typing import Dict, Any, List
import json
from datetime import datetime

from services.config import config
from services.tracking import move_live_to_finished, prune_live_trackers_keep_last_n, finished_dir_for_day

def finalize_batch_tracking(batch_id: str, track_dir: Path | None = None) -> Dict[str, Any]:
    """
    If batch is fully processed (no Pending), move its tracker to Finished/YYYY-MM-DD.
    """
    return move_live_to_finished(batch_id=batch_id, track_dir=track_dir)

def prune_live_trackers(keep_n: int | None = None) -> Dict[str, Any]:
    """
    Prune live trackers, keeping at most keep_n (defaults to NUM_LIVE_TRACKERS or TRACK_LIVE_MAX or 10).
    """
    cfg = config()
    default_keep = cfg.get("NUM_LIVE_TRACKERS", cfg.get("TRACK_LIVE_MAX", 10))
    kn = keep_n if keep_n is not None else int(default_keep)
    return prune_live_trackers_keep_last_n(keep_n=kn)

def daily_rollup_collect(day: str | None = None) -> Dict[str, Any]:
    """
    Return a parsed list of rollup entries for a given day (default = today).
    """
    d = day or datetime.now().strftime("%Y-%m-%d")
    from services.reporting import _reports_root  # local import to avoid cycle
    path = _reports_root() / "daily" / d / "rollup.ndjson"
    if not path.exists():
        return {"ok": True, "day": d, "items": []}
    items: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s:
                continue
            try:
                items.append(json.loads(s))
            except Exception:
                pass
    return {"ok": True, "day": d, "items": items}
