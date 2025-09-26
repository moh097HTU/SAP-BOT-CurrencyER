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

def write_skipped_csv(path: Path, skipped_rows: List[Dict[str, Any]]) -> None:
    """
    Mirror of write_failed_csv but for Skipped rows so we persist the SAP message.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = [
        "index", "status",
        "ExchangeRateType", "FromCurrency", "ToCurrency",
        "ValidFrom", "Quotation", "ExchangeRate",
        "dialog_text", "round",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in skipped_rows:
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
                "dialog_text": r.get("dialog_text") or r.get("error"),
                "round": r.get("round"),
            })

# ---------- daily rollup (by records' day) ----------

def _daily_dir(day: str | None = None) -> Path:
    """
    Day directory under reports/daily/<YYYY-MM-DD>.
    NOTE: 'day' should be the records' day (derived from ValidFrom), not 'today'.
    """
    d = day or datetime.now().strftime("%Y-%m-%d")
    return _reports_root() / "daily" / d

def _read_rollup_items(day: str | None = None) -> List[Dict[str, Any]]:
    ddir = _daily_dir(day)
    path = ddir / "rollup.ndjson"
    if not path.exists():
        return []
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
    return items

def rebuild_daily_final(day: str | None = None) -> Dict[str, Any]:
    """
    Build/overwrite reports/daily/<day>/final.json from the rollup file.
    Aggregates per-batch stats into day totals + a compact list of batches.
    """
    d = day or datetime.now().strftime("%Y-%m-%d")
    ddir = _daily_dir(d)
    ddir.mkdir(parents=True, exist_ok=True)

    items = _read_rollup_items(d)
    batches: List[Dict[str, Any]] = []
    totals = {"batches": 0, "received": 0, "created": 0, "failed": 0, "skipped": 0, "ok_batches": 0, "nok_batches": 0}

    for it in items:
        batch_id = it.get("batch_id")
        total = int(it.get("total", it.get("received", 0)) or 0)
        created = int(it.get("created", 0) or 0)
        failed = int(it.get("failed", 0) or 0)
        skipped = int(it.get("skipped", 0) or 0)
        ok = bool(it.get("ok"))

        batches.append({
            "batch_id": batch_id,
            "received": total,
            "created": created,
            "failed": failed,
            "skipped": skipped,
            "ok": ok,
            "reports_dir": (it.get("reports") or {}).get("dir") or "",
        })

        totals["batches"] += 1
        totals["received"] += total
        totals["created"] += created
        totals["failed"] += failed
        totals["skipped"] += skipped
        totals["ok_batches"] += 1 if ok else 0
        totals["nok_batches"] += 0 if ok else 1

    final_doc = {
        "day": d,
        "generated_at": datetime.now().isoformat(),
        "totals": totals,
        "batches": batches,
    }
    write_json(ddir / "final.json", final_doc)
    return {"ok": True, "path": str(ddir / "final.json"), "counts": totals}

def append_daily_rollup(batch_id: str, result_obj: Dict[str, Any], day: str | None = None) -> Dict[str, Any]:
    """
    Appends one JSON line per batch to reports/daily/<day>/rollup.ndjson,
    then (re)builds reports/daily/<day>/final.json.

    'day' MUST be the records' day (YYYY-MM-DD) when available.
    """
    ddir = _daily_dir(day)
    ddir.mkdir(parents=True, exist_ok=True)
    path = ddir / "rollup.ndjson"
    line = json.dumps({"batch_id": batch_id, "ts": datetime.now().isoformat(), **result_obj}, ensure_ascii=False)
    with path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")

    try:
        rebuild_daily_final(day)
    except Exception:
        pass

    return {"ok": True, "path": str(path)}

# ---------- tracker archiving/pruning (wrappers) ----------

def move_tracker_if_finished(cfg: Dict[str, Any], batch_id: str, track_dir: Path) -> Dict[str, Any]:
    return move_live_to_finished(batch_id=batch_id, track_dir=track_dir)

def prune_live_trackers(cfg: Dict[str, Any], keep_n: int = 10) -> Dict[str, Any]:
    return prune_live_trackers_keep_last_n(keep_n=keep_n)
