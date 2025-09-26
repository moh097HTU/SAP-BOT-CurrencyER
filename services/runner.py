# services/runner.py
from __future__ import annotations

import logging
import random
import shutil
import time
import threading
from pathlib import Path
from typing import Any, Dict, List, Tuple, Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed, wait, FIRST_COMPLETED
from datetime import datetime

from services.schemas import ExchangeRateItem
from services.driver import ensure_driver_binary_ready, cleanup_profiles
from services.tracking import (
    tracking_dir_for_batch,
    tracking_path_for_worker,
    init_tracking_files,
    pending_rows_for_report,
)
from services.worker import worker_process, chunk_evenly
from services.reporting import (
    ensure_reports_dir,
    write_json,
    write_failed_csv,
    write_skipped_csv,
    append_daily_rollup,
    move_tracker_if_finished,
    prune_live_trackers,
)

log = logging.getLogger("sapbot")


class BatchRunner:
    def __init__(self, cfg: Dict[str, Any], batch_id: str, reports_root: Path, workers: int):
        self.cfg = cfg
        self.batch_id = batch_id
        self.workers = max(1, int(workers))
        self.reports_root = ensure_reports_dir(reports_root)
        self.batch_dir = ensure_reports_dir(self.reports_root / batch_id)
        self.track_dir = tracking_dir_for_batch(cfg, batch_id)

    # ---------- helpers: records' day (from ValidFrom) + relocate ----------

    @staticmethod
    def _as_record_day(v: str | None) -> str | None:
        """
        Normalize ValidFrom (DD.MM.YYYY) -> YYYY-MM-DD
        """
        if not v:
            return None
        try:
            return datetime.strptime(v.strip(), "%d.%m.%Y").strftime("%Y-%m-%d")
        except Exception:
            return None

    def _record_day_from_items(self, items: List[ExchangeRateItem]) -> str | None:
        days = {self._as_record_day(it.ValidFrom) for it in items if self._as_record_day(it.ValidFrom)}
        return list(days)[0] if len(days) == 1 else None

    def _record_day_from_results(self, results: List[Dict[str, Any]]) -> str | None:
        days = set()
        for r in results:
            p = r.get("payload") or {}
            d = self._as_record_day(p.get("ValidFrom"))
            if d:
                days.add(d)
        return list(days)[0] if len(days) == 1 else None

    def _relocate_batch_under_day(self, day: str | None) -> None:
        """
        Move reports/<batch_id> → reports/<YYYY-MM-DD>/<batch_id>
        (no-op if day is None).
        """
        if not day:
            return
        target_root = ensure_reports_dir(self.reports_root / day)
        target = target_root / self.batch_id
        if str(target.resolve()) == str(self.batch_dir.resolve()):
            return
        try:
            if target.exists():
                shutil.rmtree(target, ignore_errors=True)
            shutil.move(str(self.batch_dir), str(target))
            self.batch_dir = target
        except Exception as e:
            log.error("[relocate] failed moving batch_dir into day folder %s: %s: %s", day, type(e).__name__, e)

    # ---------- internal helpers ----------

    def _run_multithread_once(self, items: List[ExchangeRateItem]) -> Dict[str, Any]:
        try:
            ensure_driver_binary_ready()
        except Exception:
            pass

        indexed = list(enumerate(items, start=1))
        shards = chunk_evenly(indexed, self.workers)
        stop_event = threading.Event()
        login_sem = threading.BoundedSemaphore(int(self.cfg.get("LOGIN_CONCURRENCY", min(2, self.workers))))

        init_tracking_files(self.track_dir, shards)

        track_files = {w_id: tracking_path_for_worker(self.track_dir, w_id)
                       for w_id, _ in enumerate(shards, start=1)}

        all_results: List[Dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            futures = []
            for w_id, shard in enumerate(shards, start=1):
                track_file = track_files[w_id]
                futures.append(pool.submit(
                    worker_process, shard, stop_event, login_sem, self.cfg, w_id, track_file
                ))

            for fut in as_completed(futures):
                try:
                    r = fut.result()
                except Exception as e:
                    r = {"results": [{
                        "index": None,
                        "status": "error",
                        "error": f"worker_crashed: {type(e).__name__}: {e}",
                    }]}
                all_results.extend(r.get("results", []))

        have_idx = {r.get("index") for r in all_results if r.get("index") is not None}
        for tf in track_files.values():
            try:
                for prow in pending_rows_for_report(tf):
                    idx = prow.get("index")
                    if idx is not None and idx not in have_idx:
                        all_results.append(prow)
                        have_idx.add(idx)
            except Exception:
                pass

        try:
            cleanup_profiles(also_base=True)
        except Exception:
            pass

        all_results.sort(key=lambda x: x.get("index") or 0)
        return {"results": all_results}

    # ---------------- PUBLIC: non-streaming ----------------
    def run_force_all_done(self, items: List[ExchangeRateItem]) -> Dict[str, Any]:
        workers = self.workers
        base_sleep = max(0, int(self.cfg.get("FORCE_ALL_DONE_BASE_SLEEP_SEC", 8)))
        max_rounds = int(self.cfg.get("FORCE_ALL_DONE_MAX_ROUNDS", 25))
        max_minutes = int(self.cfg.get("FORCE_ALL_DONE_MAX_MINUTES", 60))

        start_ts = time.time()
        time_cap = (max_minutes > 0)

        aggregate_results: Dict[int, Dict[str, Any]] = {}
        pending: List[Tuple[int, ExchangeRateItem]] = list(enumerate(items, start=1))
        round_no = 0

        try:
            while pending:
                if max_rounds > 0 and round_no >= max_rounds:
                    break
                if time_cap and (time.time() - start_ts) > (max_minutes * 60):
                    break

                round_no += 1
                round_items = [it for _, it in pending]
                r = self._run_multithread_once(round_items)
                round_rows = r.get("results", [])

                lim = min(len(round_rows), len(pending))
                for i in range(lim):
                    orig_idx = pending[i][0]
                    row = {**round_rows[i], "round": round_no}
                    aggregate_results[orig_idx] = row

                next_pending: List[Tuple[int, ExchangeRateItem]] = []
                for i in range(lim):
                    orig_idx, orig_item = pending[i]
                    row = aggregate_results.get(orig_idx, {})
                    st = (row.get("status") or "").strip().lower()
                    if st == "pending":
                        next_pending.append((orig_idx, orig_item))

                if next_pending:
                    time.sleep(base_sleep + random.uniform(0, 2.0))
                    pending = next_pending
                else:
                    pending = []

            for idx in range(1, len(items) + 1):
                aggregate_results.setdefault(idx, {
                    "index": idx,
                    "payload": items[idx - 1].dict(),
                    "status": "error",
                    "error": "no_result",
                    "round": round_no,
                })

            final_rows = [aggregate_results[i] for i in sorted(aggregate_results.keys())]
            created = sum(1 for r in final_rows if (r.get("status") or "").lower() == "created")
            failed_rows = [r for r in final_rows if (r.get("status") or "").lower() not in ("created", "skipped")]
            failed = len(failed_rows)
            skipped = sum(1 for r in final_rows if (r.get("status") or "").lower() == "skipped")
            skipped_rows = [r for r in final_rows if (r.get("status") or "").lower() == "skipped"]

            return {
                "ok": failed == 0,
                "workers": workers,
                "total": len(items),
                "created": created,
                "failed": failed,
                "skipped": skipped,
                "results": final_rows,
                "skipped_rows": skipped_rows,
                "force_all_done_rounds_used": round_no,
                "force_all_done_max_rounds": max_rounds,
                "force_all_done_time_cap_minutes": max_minutes,
                "track_dir": str(self.track_dir),
            }
        finally:
            try:
                if self.track_dir.exists():
                    shutil.rmtree(self.track_dir, ignore_errors=True)
            except Exception:
                pass

    # ---------------- PUBLIC: streaming ----------------
    def stream_events(self, items: List[ExchangeRateItem], heartbeat_sec: int = 5) -> Iterable[str]:
        start_ts = time.time()
        workers = self.workers
        base_sleep = max(0, int(self.cfg.get("FORCE_ALL_DONE_BASE_SLEEP_SEC", 8)))
        max_rounds = int(self.cfg.get("FORCE_ALL_DONE_MAX_ROUNDS", 25))
        max_minutes = int(self.cfg.get("FORCE_ALL_DONE_MAX_MINUTES", 60))
        time_cap = (max_minutes > 0)

        yield self._json_line({
            "event": "start",
            "batch_id": self.batch_id,
            "received": len(items),
            "workers": workers,
            "ts": self._iso_now(),
        })

        pending_pairs: List[Tuple[int, ExchangeRateItem]] = list(enumerate(items, start=1))
        aggregate: Dict[int, Dict[str, Any]] = {}
        round_no = 0
        all_rows_this_batch: List[Dict[str, Any]] = []

        try:
            while pending_pairs:
                if max_rounds > 0 and round_no >= max_rounds:
                    break
                if time_cap and (time.time() - start_ts) > (max_minutes * 60):
                    break

                round_no += 1
                shards = chunk_evenly(pending_pairs, workers)

                init_tracking_files(self.track_dir, shards)

                stop_event = threading.Event()
                login_sem = threading.BoundedSemaphore(int(self.cfg.get("LOGIN_CONCURRENCY", min(2, workers))))

                with ThreadPoolExecutor(max_workers=workers) as pool:
                    futures = [
                        pool.submit(
                            worker_process, shard, stop_event, login_sem, self.cfg, w_id,
                            tracking_path_for_worker(self.track_dir, w_id)
                        )
                        for w_id, shard in enumerate(shards, start=1)
                    ]

                    pending_futs = set(futures)
                    last_emit = time.time()

                    while pending_futs:
                        done, pending_futs = wait(pending_futs, timeout=heartbeat_sec, return_when=FIRST_COMPLETED)

                        for fut in done:
                            try:
                                r = fut.result()
                            except Exception as e:
                                r = {"results": [
                                    {"index": None, "status": "error",
                                     "error": f"worker_crashed: {type(e).__name__}: {e}", "round": round_no}
                                ]}
                            rows = r.get("results", [])
                            for row in rows:
                                row["round"] = round_no
                                # >>> ADD THESE LINES <<<
                                idx = row.get("index")
                                if idx is not None:
                                    aggregate[idx] = row
                                # <<<<<<<<<<<<<<<<<<<<<<<<
                            all_rows_this_batch.extend(rows)
                            for row in rows:
                                yield self._json_line({"event": "row", **row})
                            last_emit = time.time()

                        if (time.time() - last_emit) >= heartbeat_sec:
                            yield self._json_line({"event": "tick", "ts": self._iso_now()})
                            last_emit = time.time()

            results_sorted = sorted(list(aggregate.values()), key=lambda x: (x.get("index") or 0))
            created = sum(1 for r in results_sorted if (r.get("status") or "").lower() == "created")
            failed_rows = [r for r in results_sorted if (r.get("status") or "").lower() not in ("created", "skipped")]
            failed = len(failed_rows)
            skipped = sum(1 for r in results_sorted if (r.get("status") or "").lower() == "skipped")
            skipped_rows = [r for r in results_sorted if (r.get("status") or "").lower() == "skipped"]
            duration_sec = time.time() - start_ts

            result = {
                "ok": (failed == 0),
                "workers": workers,
                "total": len(items),
                "created": created,
                "failed": failed,
                "skipped": skipped,
                "results": results_sorted,
                "track_dir": str(self.track_dir),
                "force_all_done_rounds_used": round_no,
                "force_all_done_max_rounds": max_rounds,
                "force_all_done_time_cap_minutes": max_minutes,
            }

            # persist per-batch artifacts
            result_path = self.batch_dir / "result.json"
            failed_json_path = self.batch_dir / "failed.json"
            failed_csv_path = self.batch_dir / "failed.csv"
            skipped_json_path = self.batch_dir / "skipped.json"
            skipped_csv_path = self.batch_dir / "skipped.csv"

            write_json(result_path, result)
            write_json(failed_json_path, failed_rows)
            write_failed_csv(failed_csv_path, failed_rows)
            write_json(skipped_json_path, skipped_rows)
            write_skipped_csv(skipped_csv_path, skipped_rows)

            # figure records' day from the batch items and MOVE under reports/<day>/<batch_id>
            rec_day = self._record_day_from_items(items)
            self._relocate_batch_under_day(rec_day)

            # daily rollup + archive/prune (by records' day)
            try:
                append_daily_rollup(self.batch_id, {**result, "duration_sec": round(duration_sec, 2)}, day=rec_day)
            except Exception:
                pass
            try:
                _td = tracking_dir_for_batch(self.cfg, self.batch_id)
                move_tracker_if_finished(self.cfg, self.batch_id, _td)
                prune_live_trackers(self.cfg, keep_n=int(self.cfg.get("NUM_LIVE_TRACKERS", 10)))
            except Exception:
                pass

            # recompute artifact paths after potential relocate
            result_path = self.batch_dir / "result.json"
            failed_json_path = self.batch_dir / "failed.json"
            failed_csv_path = self.batch_dir / "failed.csv"
            skipped_json_path = self.batch_dir / "skipped.json"
            skipped_csv_path = self.batch_dir / "skipped.csv"

            yield self._json_line({
                "event": "end",
                "batch_id": self.batch_id,
                "received": len(items),
                "duration_sec": round(duration_sec, 2),
                "created": created,
                "failed": failed,
                "skipped": skipped,
                "reports": {
                    "dir": str(self.batch_dir),
                    "result_json": str(result_path),
                    "failed_json": str(failed_json_path),
                    "failed_csv": str(failed_csv_path),
                    "skipped_json": str(skipped_json_path),
                    "skipped_csv": str(skipped_csv_path),
                },
                "email": {"ok": False, "reason": "not_requested"},
                "track_dir": str(self.track_dir),
                "records_day": rec_day,
            })

        finally:
            try:
                if self.track_dir.exists():
                    shutil.rmtree(self.track_dir, ignore_errors=True)
            except Exception:
                pass

    # ---------- reporting helpers used by routes ----------

    def write_request_summary(self, items_sample: List[Dict[str, Any]], workers: int) -> None:
        from datetime import datetime
        write_json(self.batch_dir / "request.json", {
            "batch_id": self.batch_id,
            "received": len(items_sample),
            "ts": datetime.now().isoformat(),
            "workers": workers,
            "sample": items_sample[:5],
        })

    def persist_and_email(self, result: Dict[str, Any], duration_sec: float) -> Dict[str, Any]:
        results = result.get("results", [])
        failed_rows = [r for r in results if (r.get("status") or "").lower() not in ("created", "skipped")]
        skipped_rows = [r for r in results if (r.get("status") or "").lower() == "skipped"]

        result_path = self.batch_dir / "result.json"
        failed_json_path = self.batch_dir / "failed.json"
        failed_csv_path = self.batch_dir / "failed.csv"
        skipped_json_path = self.batch_dir / "skipped.json"
        skipped_csv_path = self.batch_dir / "skipped.csv"

        write_json(result_path, result)
        write_json(failed_json_path, failed_rows)
        write_failed_csv(failed_csv_path, failed_rows)
        write_json(skipped_json_path, skipped_rows)
        write_skipped_csv(skipped_csv_path, skipped_rows)

        # relocate under records' day (derived from results payloads)
        rec_day = self._record_day_from_results(results)
        self._relocate_batch_under_day(rec_day)

        # Email summary if enabled & there are failures
        email_info = {"ok": False, "reason": "not_requested"}
        if self.cfg.get("EMAIL_ENABLED") and failed_rows:
            try:
                from services.notify import send_batch_email
                attachments = [str(self.batch_dir / "failed.json"), str(self.batch_dir / "failed.csv")]
                email_info = send_batch_email(
                    batch_id=self.batch_id,
                    received_count=result.get("total", 0),
                    result_obj=result,
                    failed_rows=failed_rows,
                    attachment_paths=attachments,
                    duration_sec=duration_sec,
                )
            except Exception as e:
                email_info = {"ok": False, "reason": f"send_error: {type(e).__name__}: {e}"}

        # paths may have changed after relocate
        result_out = dict(result)
        result_out.update({
            "batch_id": self.batch_id,
            "duration_sec": round(duration_sec, 2),
            "reports": {
                "dir": str(self.batch_dir),
                "result_json": str(self.batch_dir / "result.json"),
                "failed_json": str(self.batch_dir / "failed.json"),
                "failed_csv": str(self.batch_dir / "failed.csv"),
                "skipped_json": str(self.batch_dir / "skipped.json"),
                "skipped_csv": str(self.batch_dir / "skipped.csv"),
            },
            "email": email_info,
            "records_day": rec_day,
        })

        # Append to daily rollup for that records' day
        try:
            append_daily_rollup(self.batch_id, result_out, day=rec_day)
        except Exception:
            pass

        # Archive tracker & prune
        try:
            from services.tracking import tracking_dir_for_batch
            _td = tracking_dir_for_batch(self.cfg, self.batch_id)
            move_tracker_if_finished(self.cfg, self.batch_id, _td)
            prune_live_trackers(self.cfg, keep_n=int(self.cfg.get("NUM_LIVE_TRACKERS", 10)))
        except Exception:
            pass

        return result_out

    # ---------- small utils ----------

    @staticmethod
    def _json_line(obj: Dict[str, Any]) -> str:
        import json
        return json.dumps(obj) + "\n"

    @staticmethod
    def _iso_now() -> str:
        from datetime import datetime
        return datetime.now().isoformat()
