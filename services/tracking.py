# services/tracking.py
from __future__ import annotations

from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional
import json
import shutil
from datetime import datetime

from services.schemas import ExchangeRateItem
from services.config import config

# ---- Standardized tracker status tokens ----
PENDING = "Pending"
DONE    = "Done"
SKIPPED = "Skipped"

# ---- Directory layout helpers ----

def _root() -> Path:
    """Base tracking root from env TRACK_DIR (default WebService/TrackDrivers)."""
    return Path(config().get("TRACK_DIR") or "WebService/TrackDrivers").resolve()

def _live_root() -> Path:
    p = _root() / "Live"
    p.mkdir(parents=True, exist_ok=True)
    return p

def _finished_root_for_day(day: Optional[str] = None) -> Path:
    d = day or datetime.now().strftime("%Y-%m-%d")
    p = _root() / "Finished" / d
    p.mkdir(parents=True, exist_ok=True)
    return p

def finished_dir_for_day(day: Optional[str] = None) -> Path:
    """Public getter to be used by reporting/daily."""
    return _finished_root_for_day(day)

def tracking_dir_for_batch(cfg: Dict[str, Any], batch_id: str) -> Path:
    """Per-batch live tracker dir."""
    d = _live_root() / batch_id
    d.mkdir(parents=True, exist_ok=True)
    return d

def tracking_path_for_worker(track_dir: Path, worker_id: int) -> Path:
    return track_dir / f"driver-{worker_id}.json"

# ---- File IO helpers ----

def _load_tracking(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"worker_id": None, "items": []}

def _save_tracking_atomic(path: Path, doc: Dict[str, Any]) -> None:
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)

# ---- Initialize / Update ----

def init_tracking_files(track_dir: Path, shards: List[List[Tuple[int, ExchangeRateItem]]]) -> None:
    """
    Create one JSON per worker with each row initialized as Pending.
    """
    track_dir.mkdir(parents=True, exist_ok=True)
    for w_id, shard in enumerate(shards, start=1):
        path = tracking_path_for_worker(track_dir, w_id)
        if path.exists():
            # keep existing (supports driver restarts)
            continue
        doc = {
            "worker_id": w_id,
            "items": [{"index": idx, "status": PENDING, "payload": it.dict()} for (idx, it) in shard],
        }
        _save_tracking_atomic(path, doc)

def mark_item_status(path: Path, index: int, status: str, extra: Optional[Dict[str, Any]] = None) -> None:
    """
    Update a single item inside a worker tracking file.
    status should be one of: Pending / Done / Skipped / Error ...
    """
    doc = _load_tracking(path)
    changed = False
    for row in doc.get("items", []):
        if row.get("index") == index:
            row["status"] = status
            if extra:
                row.update(extra)
            changed = True
            break
    if changed:
        _save_tracking_atomic(path, doc)

def iter_pending_items(path: Path) -> List[Tuple[int, ExchangeRateItem]]:
    """
    Only return items currently Pending in this track file.
    """
    doc = _load_tracking(path)
    out: List[Tuple[int, ExchangeRateItem]] = []
    changed = False
    for row in doc.get("items", []):
        st = (row.get("status") or "").strip()
        if st.lower() == PENDING.lower():
            payload = row.get("payload") or {}
            try:
                item = ExchangeRateItem(**payload)
                out.append((row.get("index"), item))
            except Exception:
                # malformed → mark Error to avoid loops
                row["status"] = "Error"
                changed = True
    if changed:
        _save_tracking_atomic(path, doc)
    return out

def pending_rows_for_report(path: Path) -> list[dict]:
    """
    Synthesize rows for reporting for remaining Pending items.
    """
    doc = _load_tracking(path)
    out: list[dict] = []
    for row in doc.get("items", []):
        if (row.get("status") or "").strip().lower() == PENDING.lower():
            out.append({
                "index": row.get("index"),
                "status": PENDING,
                "payload": row.get("payload") or {},
            })
    return out

# ---- Live -> Finished archiving & pruning ----

def _dir_has_any_pending(track_dir: Path) -> bool:
    for f in sorted(track_dir.glob("driver-*.json")):
        doc = _load_tracking(f)
        for row in doc.get("items", []):
            if (row.get("status") or "").strip().lower() == PENDING.lower():
                return True
    return False

def move_live_to_finished(batch_id: str, track_dir: Optional[Path] = None, day: Optional[str] = None) -> Dict[str, Any]:
    """
    If the batch's live tracker has NO Pending rows, move it under Finished/YYYY-MM-DD/<batch_id>.
    Returns a dict describing the action.
    """
    lr = _live_root()
    tdir = track_dir or (lr / batch_id)
    if not tdir.exists():
        return {"ok": False, "reason": "no_live_dir", "batch_id": batch_id}

    if _dir_has_any_pending(tdir):
        return {"ok": False, "reason": "still_pending", "batch_id": batch_id, "path": str(tdir)}

    dest_root = _finished_root_for_day(day)
    dest = dest_root / batch_id
    try:
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        shutil.move(str(tdir), str(dest))
        return {"ok": True, "moved_to": str(dest), "batch_id": batch_id}
    except Exception as e:
        return {"ok": False, "reason": f"move_failed: {type(e).__name__}: {e}", "batch_id": batch_id}

def prune_live_trackers_keep_last_n(keep_n: int = 10) -> Dict[str, Any]:
    """
    Keep only the most-recent N live batch tracker dirs by mtime; delete older ones.
    """
    keep_n = max(0, int(keep_n))
    lr = _live_root()
    if not lr.exists():
        return {"ok": True, "deleted": [], "kept": []}

    dirs = [d for d in lr.iterdir() if d.is_dir()]
    dirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)

    to_keep = dirs[:keep_n] if keep_n > 0 else []
    to_delete = dirs[keep_n:] if keep_n >= 0 else []

    deleted = []
    for d in to_delete:
        try:
            shutil.rmtree(d, ignore_errors=True)
            deleted.append(str(d))
        except Exception:
            pass

    return {"ok": True, "deleted": deleted, "kept": [str(p) for p in to_keep]}

# ---- Live status summary (for routes/currency.py) ----

def _count_statuses_in_doc(doc: Dict[str, Any]) -> Dict[str, int]:
    """
    Count normalized statuses in a single tracking doc.
    Normalization: 'created' -> Done, 'skipped' -> Skipped, 'pending' -> Pending.
    Anything else -> Error.
    """
    counts = {DONE: 0, SKIPPED: 0, PENDING: 0, "Error": 0}
    for row in doc.get("items", []):
        raw = (row.get("status") or "").strip().lower()
        if raw == "done" or raw == "created":
            counts[DONE] += 1
        elif raw == "skipped":
            counts[SKIPPED] += 1
        elif raw == "pending":
            counts[PENDING] += 1
        else:
            counts["Error"] += 1
    return counts

def read_live_status_summary(batch_id: Optional[str] = None, track_dir: Optional[Path] = None) -> Dict[str, Any]:
    """
    Summarize the live tracker(s).
    - If track_dir is provided, summarize that directory.
    - Else if batch_id is provided, summarize Live/<batch_id>.
    - Else, summarize ALL batches under Live/.
    Returns dict with totals and per-worker breakdown (when summarizing a single batch).
    """
    lr = _live_root()
    if track_dir is None:
        if batch_id:
            track_dir = lr / batch_id
        else:
            # global summary across all live batches
            batches = []
            for bdir in sorted([d for d in lr.iterdir() if d.is_dir()]):
                b_tot = {DONE: 0, SKIPPED: 0, PENDING: 0, "Error": 0}
                for f in sorted(bdir.glob("driver-*.json")):
                    doc = _load_tracking(f)
                    c = _count_statuses_in_doc(doc)
                    for k, v in c.items():
                        b_tot[k] = b_tot.get(k, 0) + int(v)
                batches.append({"batch_id": bdir.name, "totals": b_tot, "path": str(bdir)})
            grand = {DONE: 0, SKIPPED: 0, PENDING: 0, "Error": 0}
            for b in batches:
                for k, v in b["totals"].items():
                    grand[k] = grand.get(k, 0) + int(v)
            return {"ok": True, "scope": "all", "totals": grand, "batches": batches, "live_root": str(lr)}

    # single batch dir summary
    if not track_dir.exists():
        return {"ok": False, "reason": "not_found", "path": str(track_dir)}
    by_worker = []
    totals = {DONE: 0, SKIPPED: 0, PENDING: 0, "Error": 0}
    for f in sorted(track_dir.glob("driver-*.json")):
        doc = _load_tracking(f)
        wid = doc.get("worker_id")
        c = _count_statuses_in_doc(doc)
        by_worker.append({"worker_id": wid, "file": f.name, "totals": c})
        for k, v in c.items():
            totals[k] = totals.get(k, 0) + int(v)

    return {
        "ok": True,
        "scope": "batch",
        "batch_id": batch_id or track_dir.name,
        "path": str(track_dir),
        "totals": totals,
        "by_worker": by_worker,
        "has_pending": totals.get(PENDING, 0) > 0,
    }
