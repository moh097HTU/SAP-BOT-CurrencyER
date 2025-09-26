# services/reporting.py
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List
import json
import csv
from datetime import datetime

from services.config import config
from services.tracking import move_live_to_finished, prune_live_trackers_keep_last_n

# ---------- file utils ----------

def ensure_reports_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path

def _reports_root() -> Path:
    base = Path(config().get("REPORTS_DIR") or "reports").resolve()
    base.mkdir(parents=True, exist_ok=True)
    return base

def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")

def write_failed_csv(path: Path, failed_rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = [
        "index", "status",
        "ExchangeRateType", "FromCurrency", "ToCurrency",
        "ValidFrom", "Quotation", "ExchangeRate",
        "error", "dialog_text", "lock_table", "lock_owner", "round",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in failed_rows:
            p = r.get("payload", {}) or {}
            w.writerow({
                "index": r.get("index"),
                "status": r.get("status"),
                "ExchangeRateType": p.get("ExchangeRateType"),
                "FromCurrency": p.get("FromCurrency"),
                "ToCurrency": p.get("ToCurrency"),
                "ValidFrom": p.get("ValidFrom"),
                "Quotation": p.get("Quotation"),
                "ExchangeRate": p.get("ExchangeRate"),
                "error": r.get("error"),
                "dialog_text": r.get("dialog_text"),
                "lock_table": r.get("lock_table"),
                "lock_owner": r.get("lock_owner"),
                "round": r.get("round"),
            })

# ---------- daily rollup ----------

def _daily_dir() -> Path:
    return _reports_root() / "daily" / datetime.now().strftime("%Y-%m-%d")

def append_daily_rollup(batch_id: str, result_obj: Dict[str, Any]) -> Dict[str, Any]:
    """
    Appends one JSON line per batch to reports/daily/YYYY-MM-DD/rollup.ndjson
    """
    ddir = _daily_dir()
    ddir.mkdir(parents=True, exist_ok=True)
    path = ddir / "rollup.ndjson"
    line = json.dumps({"batch_id": batch_id, "ts": datetime.now().isoformat(), **result_obj}, ensure_ascii=False)
    with path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    return {"ok": True, "path": str(path)}

# ---------- tracker archiving/pruning (wrappers) ----------

def move_tracker_if_finished(cfg: Dict[str, Any], batch_id: str, track_dir: Path) -> Dict[str, Any]:
    """
    Check if a batch tracker has any Pending; if none → move to Finished/YYYY-MM-DD.
    """
    return move_live_to_finished(batch_id=batch_id, track_dir=track_dir)

def prune_live_trackers(cfg: Dict[str, Any], keep_n: int = 10) -> Dict[str, Any]:
    """
    Keep only last N live trackers (by mtime) to avoid bloat.
    """
    return prune_live_trackers_keep_last_n(keep_n=keep_n)
