# routes/currency.py
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, validator
from typing import List, Dict, Any, Optional, Tuple
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime
from pathlib import Path
import time
import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed, wait, FIRST_COMPLETED
import json
import csv
import uuid
import os

from selenium.common.exceptions import (
    InvalidSessionIdException,
    WebDriverException,
    NoSuchWindowException,
    TimeoutException,
)

from services.config import config
from services.driver import get_driver, ensure_driver_binary_ready
from services.auth import login
from services.ui import (
    wait_for_shell_home,
    wait_ui5_idle,
    wait_url_contains,
    wait_shell_search_ready,
)
from services.notify import send_batch_email
from services.commit import commit_gate   # <-- use the real gate
from pages.Shell.Search.element import ShellSearch
from pages.CurrencyExchangeRates.page import CurrencyExchangeRatesPage

router = APIRouter()

# ------------------- Models -------------------

class ExchangeRateItem(BaseModel):
    ExchangeRateType: str = Field(..., description="e.g. M")
    FromCurrency: str = Field(..., description="e.g. USD")
    ToCurrency: str = Field(..., description="e.g. JOD")
    ValidFrom: str = Field(..., description="Date like 2025-31-12 (YYYY-DD-MM) or other common formats")
    Quotation: Optional[str] = Field("Direct", description="Direct or Indirect")
    ExchangeRate: str | float | Decimal = Field(..., description="> 0; rounded to 5 dp")

    @validator("ExchangeRateType", "FromCurrency", "ToCurrency")
    def _up(cls, v: str):  # noqa: N805
        return (v or "").strip().upper()

    @validator("Quotation", always=True)
    def _q(cls, v: Optional[str]):  # noqa: N805
        s = (v or "Direct").strip().capitalize()
        return "Indirect" if s.startswith("Ind") else "Direct"

    @validator("ValidFrom")
    def _datefmt(cls, v: str):  # noqa: N805
        """
        Normalize any accepted date input to SAP typing format: YYYY-DD-MM.
        """
        s = (v or "").strip()
        fmts = [
            "%m/%d/%Y",   # 12/31/2025
            "%Y-%m-%d",   # 2025-12-31
            "%Y/%m/%d",   # 2025/12/31
            "%d/%m/%Y",   # 31/12/2025
            "%Y%m%d",     # 20251231
            "%Y-%d-%m",   # 2025-31-12 (target) accepted too
        ]
        for f in fmts:
            try:
                dt = datetime.strptime(s, f)
                return dt.strftime("%Y-%d-%m")
            except Exception:
                pass
        raise ValueError(f"Unrecognized date: {v}")

    @validator("ExchangeRate")
    def _5dp(cls, v):  # noqa: N805
        q = Decimal(str(v))
        if q <= 0:
            raise ValueError("ExchangeRate must be > 0")
        q = q.quantize(Decimal("0.00001"), rounding=ROUND_HALF_UP)
        return f"{q:.5f}"

# ------------------- App open helpers -------------------

def _open_currency_app(drv) -> CurrencyExchangeRatesPage:
    """
    Open FLP → Global Search → Currency Exchange Rates app, then ensure list is ready.
    """
    if not wait_for_shell_home(drv, timeout=60):
        raise RuntimeError("Shell home not detected after login")
    wait_ui5_idle(drv, timeout=30)
    wait_shell_search_ready(drv, timeout=30)

    ShellSearch(drv).open_search().type_and_choose_app("Currency Exchange Rates")
    wait_ui5_idle(drv, timeout=30)
    wait_url_contains(drv, "#Currency-maintainExchangeRates", 40)

    page = CurrencyExchangeRatesPage(drv)
    page.ensure_in_app(max_attempts=3, settle_each=8)
    return page

def _is_fatal_session_err(err: Exception) -> bool:
    msg = (str(err) or "").lower()
    return isinstance(err, (InvalidSessionIdException, NoSuchWindowException)) or any(
        s in msg
        for s in [
            "invalid session id",
            "chrome not reachable",
            "target closed",
            "disconnected: not connected to devtools",
            "cannot determine loading status",
        ]
    )

def _chunk_evenly(seq: List[Tuple[int, ExchangeRateItem]], n: int):
    n = max(1, min(n, len(seq)))
    k, m = divmod(len(seq), n)
    chunks = []
    start = 0
    for i in range(n):
        end = start + k + (1 if i < m else 0)
        if start < end:
            chunks.append(seq[start:end])
        start = end
    return chunks

# ------------------- Worker -------------------

def _worker_process(
    shard: List[Tuple[int, ExchangeRateItem]],
    stop_event: threading.Event,
    login_sem: threading.Semaphore,
    cfg: Dict[str, Any],
    worker_id: int,
    commit_lock: threading.Lock,  # kept for compatibility; NOT used now
) -> Dict[str, Any]:
    """
    Per-thread worker. Own Chrome session.
    Only the footer Create/Activate is serialized via commit_gate (narrow critical section).
    """
    results: List[Dict[str, Any]] = []
    drv = None
    page = None

    WATCHDOG_SECONDS = int(cfg.get("WATCHDOG_SECONDS", 120))
    MAX_OPEN_RETRIES = 3

    def _kill_driver():
        nonlocal drv
        try:
            if drv:
                drv.quit()
        except Exception:
            pass

    def _recreate_driver_and_reopen(max_open_retries: int = MAX_OPEN_RETRIES):
        nonlocal drv, page
        _kill_driver()
        drv = get_driver(headless=cfg["HEADLESS"])
        with login_sem:
            login(drv)
        wait_ui5_idle(drv, timeout=30)

        last_exc = None
        for attempt in range(1, max_open_retries + 1):
            try:
                page_local = _open_currency_app(drv)
                return page_local
            except Exception as e:
                last_exc = e
                time.sleep(1.0 * attempt)  # linear backoff
        raise RuntimeError(f"open_app_failed after {max_open_retries} attempts: {last_exc}")

    try:
        try:
            page = _recreate_driver_and_reopen()
        except Exception as e:
            for idx, it in shard:
                results.append(
                    {
                        "index": idx,
                        "payload": it.dict(),
                        "status": "error",
                        "error": f"init_failed(w{worker_id}): {type(e).__name__}: {e}",
                        "worker": worker_id,
                    }
                )
            return {"interrupted": False, "results": results}

        for idx, it in shard:
            if stop_event.is_set():
                stop_event.clear()

            attempt = 0
            timer = threading.Timer(WATCHDOG_SECONDS, _kill_driver)
            timer.daemon = True
            timer.start()

            try:
                # NO outer global lock here. Pass the *narrow* commit gate to the page.
                res = page.create_rate(
                    exch_type=it.ExchangeRateType,
                    from_ccy=it.FromCurrency,
                    to_ccy=it.ToCurrency,
                    valid_from_mmddyyyy=it.ValidFrom,  # naming kept for compatibility
                    quotation=it.Quotation,
                    rate_value=it.ExchangeRate,
                    commit_gate=commit_gate,          # <-- narrow critical section only
                )
                out = {"index": idx, "payload": it.dict(), **res, "worker": worker_id}
                results.append(out)
                time.sleep(0.2)

            except WebDriverException as e:
                if _is_fatal_session_err(e) or attempt == 0:
                    try:
                        page = _recreate_driver_and_reopen(max_open_retries=2)
                        attempt += 1
                        try:
                            res = page.create_rate(
                                exch_type=it.ExchangeRateType,
                                from_ccy=it.FromCurrency,
                                to_ccy=it.ToCurrency,
                                valid_from_mmddyyyy=it.ValidFrom,
                                quotation=it.Quotation,
                                rate_value=it.ExchangeRate,
                                commit_gate=commit_gate,
                            )
                            out = {"index": idx, "payload": it.dict(), **res, "worker": worker_id}
                            results.append(out)
                        except Exception as e2:
                            results.append(
                                {
                                    "index": idx,
                                    "payload": it.dict(),
                                    "status": "error",
                                    "error": f"recover_failed(w{worker_id}): {type(e2).__name__}: {e2}",
                                    "worker": worker_id,
                                }
                            )
                    except Exception as e2:
                        results.append(
                            {
                                "index": idx,
                                "payload": it.dict(),
                                "status": "error",
                                "error": f"reopen_failed(w{worker_id}): {type(e2).__name__}: {e2}",
                                "worker": worker_id,
                            }
                        )
                else:
                    results.append(
                        {
                            "index": idx,
                            "payload": it.dict(),
                            "status": "error",
                            "error": f"{type(e).__name__}(w{worker_id}): {e}",
                            "worker": worker_id,
                        }
                    )
            finally:
                try:
                    timer.cancel()
                except Exception:
                    pass

    finally:
        if not cfg.get("KEEP_BROWSER"):
            try:
                if drv:
                    drv.quit()
            except Exception:
                pass

    return {"interrupted": False, "results": results}

# ------------------- Coordinator -------------------

def _run_multithread(items: List[ExchangeRateItem], workers: int, cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Run shards across N workers; aggregate results."""
    try:
        ensure_driver_binary_ready()
    except Exception:
        pass

    indexed = list(enumerate(items, start=1))
    shards = _chunk_evenly(indexed, workers)
    stop_event = threading.Event()

    login_sem = threading.BoundedSemaphore(int(cfg.get("LOGIN_CONCURRENCY", min(2, workers))))
    commit_lock = threading.Lock()  # kept for compatibility; no longer used in workers

    all_results: List[Dict[str, Any]] = []

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = []
        for w_id, shard in enumerate(shards, start=1):
            futures.append(
                pool.submit(_worker_process, shard, stop_event, login_sem, cfg, w_id, commit_lock)
            )

        for fut in as_completed(futures):
            r = fut.result()
            all_results.extend(r.get("results", []))

    all_results.sort(key=lambda x: x.get("index", 0))

    created = sum(1 for r in all_results if r.get("status") == "created")
    failed = sum(1 for r in all_results if r.get("status") in ("validation_error", "error", "unknown", "dialog_open"))
    skipped = sum(1 for r in all_results if r.get("status") == "skipped")
    interrupted = False

    return {
        "ok": (failed == 0) and (not interrupted),
        "workers": workers,
        "total": len(items),
        "created": created,
        "failed": failed,
        "skipped": skipped,
        "interrupted_by_dialog": interrupted,
        "results": all_results,
    }

# ------------------- Reporting utils -------------------

def _ensure_reports_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path

def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")

def _write_failed_csv(path: Path, failed_rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = [
        "index", "status",
        "ExchangeRateType", "FromCurrency", "ToCurrency",
        "ValidFrom", "Quotation", "ExchangeRate",
        "error", "dialog_text"
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
            })

# ------------------- API (single JSON at end) -------------------

@router.post("/currency/exchange-rates/batch")
async def create_exchange_rates(items: List[ExchangeRateItem]) -> Dict[str, Any]:
    cfg = config()
    workers = int(cfg.get("NUM_WORKERS", 6)) or 6

    received_count = len(items)
    batch_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + str(uuid.uuid4())[:8]
    reports_root = _ensure_reports_dir(Path(cfg.get("REPORTS_DIR") or "reports"))
    batch_dir = _ensure_reports_dir(reports_root / batch_id)

    req_summary = {
        "batch_id": batch_id,
        "received": received_count,
        "ts": datetime.now().isoformat(),
        "workers": workers,
        "sample": [it.dict() for it in items[:5]],
    }
    _write_json(batch_dir / "request.json", req_summary)

    start_ts = time.time()

    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(None, lambda: _run_multithread(items, workers, cfg))
    except Exception as e:
        result = {
            "ok": False,
            "workers": workers,
            "total": received_count,
            "created": 0,
            "failed": received_count,
            "skipped": 0,
            "interrupted_by_dialog": False,
            "error": f"batch_failed: {type(e).__name__}: {e}",
            "results": [],
        }

    duration_sec = time.time() - start_ts

    results = result.get("results", [])
    failed_rows = [r for r in results if r.get("status") != "created"]

    result_path = batch_dir / "result.json"
    failed_json_path = batch_dir / "failed.json"
    failed_csv_path = batch_dir / "failed.csv"
    _write_json(result_path, result)
    _write_json(failed_json_path, failed_rows)
    _write_failed_csv(failed_csv_path, failed_rows)

    email_info = {"ok": False, "reason": "not_requested"}
    if cfg.get("EMAIL_ENABLED") and failed_rows:
        try:
            attachments = [str(failed_json_path), str(failed_csv_path)]
            email_info = send_batch_email(
                batch_id=batch_id,
                received_count=received_count,
                result_obj=result,
                failed_rows=failed_rows,
                attachment_paths=attachments,
                duration_sec=duration_sec,
            )
        except Exception as e:
            email_info = {"ok": False, "reason": f"send_error: {type(e).__name__}: {e}"}

    out = {
        **result,
        "batch_id": batch_id,
        "received": received_count,
        "duration_sec": round(duration_sec, 2),
        "reports": {
            "dir": str(batch_dir),
            "result_json": str(result_path),
            "failed_json": str(failed_json_path),
            "failed_csv": str(failed_csv_path),
        },
        "email": email_info,
    }
    return out

# ------------------- Streaming (optional, unchanged from earlier) -------------------

@router.post("/currency/exchange-rates/batch/stream")
async def create_exchange_rates_stream(items: List[ExchangeRateItem]):
    cfg = config()
    workers = int(cfg.get("NUM_WORKERS", 6)) or 6

    received_count = len(items)
    batch_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + str(uuid.uuid4())[:8]
    reports_root = _ensure_reports_dir(Path(cfg.get("REPORTS_DIR") or "reports"))
    batch_dir = _ensure_reports_dir(reports_root / batch_id)

    req_summary = {
        "batch_id": batch_id,
        "received": received_count,
        "ts": datetime.now().isoformat(),
        "workers": workers,
        "sample": [it.dict() for it in items[:5]],
    }
    _write_json(batch_dir / "request.json", req_summary)

    HEARTBEAT_SEC = 5

    def _generator():
        start_ts = time.time()
        yield json.dumps({
            "event": "start",
            "batch_id": batch_id,
            "received": received_count,
            "workers": workers,
            "ts": datetime.now().isoformat(),
        }) + "\n"

        try:
            ensure_driver_binary_ready()
        except Exception:
            pass

        indexed = list(enumerate(items, start=1))
        shards = _chunk_evenly(indexed, workers)
        stop_event = threading.Event()
        login_sem = threading.BoundedSemaphore(int(cfg.get("LOGIN_CONCURRENCY", min(2, workers))))
        commit_lock = threading.Lock()  # not used inside worker anymore

        all_results: List[Dict[str, Any]] = []

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(_worker_process, shard, stop_event, login_sem, cfg, w_id, commit_lock)
                       for w_id, shard in enumerate(shards, start=1)]

            pending = set(futures)
            last_emit = time.time()

            while pending:
                done, pending = wait(pending, timeout=HEARTBEAT_SEC, return_when=FIRST_COMPLETED)

                for fut in done:
                    try:
                        r = fut.result()
                    except Exception as e:
                        r = {"results": [
                            {"index": None, "status": "error", "error": f"worker_crashed: {type(e).__name__}: {e}"}
                        ]}
                    rows = r.get("results", [])
                    all_results.extend(rows)
                    for row in rows:
                        yield json.dumps({"event": "row", **row}) + "\n"
                    last_emit = time.time()

                if (time.time() - last_emit) >= HEARTBEAT_SEC:
                    yield json.dumps({"event": "tick", "ts": datetime.now().isoformat()}) + "\n"
                    last_emit = time.time()

        all_results.sort(key=lambda x: (x.get("index") or 0))
        created = sum(1 for r in all_results if r.get("status") == "created")
        failed_rows = [r for r in all_results if r.get("status") != "created"]
        failed = len(failed_rows)
        skipped = sum(1 for r in all_results if r.get("status") == "skipped")
        interrupted = False
        duration_sec = time.time() - start_ts

        result = {
            "ok": (failed == 0) and (not interrupted),
            "workers": workers,
            "total": received_count,
            "created": created,
            "failed": failed,
            "skipped": skipped,
            "interrupted_by_dialog": interrupted,
            "results": all_results,
        }

        result_path = batch_dir / "result.json"
        failed_json_path = batch_dir / "failed.json"
        failed_csv_path = batch_dir / "failed.csv"
        _write_json(result_path, result)
        _write_json(failed_json_path, failed_rows)
        _write_failed_csv(failed_csv_path, failed_rows)

        email_info = {"ok": False, "reason": "not_requested"}
        if cfg.get("EMAIL_ENABLED") and failed_rows:
            try:
                attachments = [str(failed_json_path), str(failed_csv_path)]
                email_info = send_batch_email(
                    batch_id=batch_id,
                    received_count=received_count,
                    result_obj=result,
                    failed_rows=failed_rows,
                    attachment_paths=attachments,
                    duration_sec=duration_sec,
                )
            except Exception as e:
                email_info = {"ok": False, "reason": f"send_error: {type(e).__name__}: {e}"}

        yield json.dumps({
            "event": "end",
            "batch_id": batch_id,
            "received": received_count,
            "duration_sec": round(duration_sec, 2),
            "created": created,
            "failed": failed,
            "skipped": skipped,
            "reports": {
                "dir": str(batch_dir),
                "result_json": str(result_path),
                "failed_json": str(failed_json_path),
                "failed_csv": str(failed_csv_path),
            },
            "email": email_info,
        }) + "\n"

    return StreamingResponse(_generator(), media_type="application/x-ndjson")
