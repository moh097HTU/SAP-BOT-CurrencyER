# routes/currency.py
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field, validator
from typing import List, Dict, Any, Optional, Tuple
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime
import time
import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

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
from pages.Shell.Search.element import ShellSearch
from pages.CurrencyExchangeRates.page import CurrencyExchangeRatesPage

router = APIRouter()


# ------------------- Models -------------------

class ExchangeRateItem(BaseModel):
    ExchangeRateType: str = Field(..., description="e.g. M")
    FromCurrency: str = Field(..., description="e.g. USD")
    ToCurrency: str = Field(..., description="e.g. JOD")
    ValidFrom: str = Field(..., description="Date like 12/31/2025 or 2025-12-31")
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
        s = (v or "").strip()
        fmts = ["%m/%d/%Y", "%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%Y%m%d"]
        for f in fmts:
            try:
                return datetime.strptime(s, f).strftime("%m/%d/%Y")
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

    # Use global search (with its own deep-link fallback)
    ShellSearch(drv).open_search().type_and_choose_app("Currency Exchange Rates")
    wait_ui5_idle(drv, timeout=30)
    wait_url_contains(drv, "#Currency-maintainExchangeRates", 40)

    page = CurrencyExchangeRatesPage(drv)
    # Important: in tenants with FCL side column default, ensure list is usable
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
    commit_lock: threading.Lock,   # kept for compatibility; not used
) -> Dict[str, Any]:
    """
    Per-thread worker. Owns its own Chrome profile + session.

    Watchdog logic:
      - For each item we arm a timer (WATCHDOG_SECONDS, default 120).
      - If the UI hangs (e.g. FLP froze, page modal blocked, profile contention),
        the watchdog kills the driver → create_rate raises → we rebuild and retry once.
    """
    # Global commit gate (serialize only Create/Activate)
    from services.commit import commit_gate

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
        # New isolated Chrome with its own user-data-dir (services/driver.py)
        drv = get_driver(headless=cfg["HEADLESS"])

        # Gate SSO so we don't hammer the IdP
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
        # Initialize this worker
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
                    }
                )
            return {"interrupted": False, "results": results}

        for idx, it in shard:
            if stop_event.is_set():
                results.append(
                    {
                        "index": idx,
                        "payload": it.dict(),
                        "status": "skipped",
                        "reason": "interrupted_by_dialog_in_other_worker",
                    }
                )
                continue

            attempt = 0
            while True:
                # --- Arm watchdog ---
                timer = threading.Timer(WATCHDOG_SECONDS, _kill_driver)
                timer.daemon = True
                timer.start()

                try:
                    # Parallelize everything up to submit; serialize only Create/Activate via commit_gate
                    res = page.create_rate(
                        exch_type=it.ExchangeRateType,
                        from_ccy=it.FromCurrency,
                        to_ccy=it.ToCurrency,
                        valid_from_mmddyyyy=it.ValidFrom,
                        quotation=it.Quotation,
                        rate_value=it.ExchangeRate,
                        commit_gate=commit_gate,  # <── key change
                    )

                    out = {"index": idx, "payload": it.dict(), **res, "worker": worker_id}
                    results.append(out)

                    if res.get("status") == "dialog_open":
                        stop_event.set()  # stop others cleanly

                    time.sleep(0.2)
                    break

                except WebDriverException as e:
                    # If watchdog killed the driver or we lost the session, rebuild once
                    if _is_fatal_session_err(e) or attempt == 0:
                        try:
                            page = _recreate_driver_and_reopen(max_open_retries=2)
                            attempt += 1
                            continue
                        except Exception as e2:
                            results.append(
                                {
                                    "index": idx,
                                    "payload": it.dict(),
                                    "status": "error",
                                    "error": f"recover_failed(w{worker_id}): {type(e2).__name__}: {e2}",
                                }
                            )
                            break
                    # Other webdriver error → record and move on
                    results.append(
                        {
                            "index": idx,
                            "payload": it.dict(),
                            "status": "error",
                            "error": f"{type(e).__name__}(w{worker_id}): {e}",
                        }
                    )
                    break

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

    return {"interrupted": stop_event.is_set(), "results": results}

# ------------------- Coordinator -------------------

def _run_multithread(items: List[ExchangeRateItem], workers: int, cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Run shards across N workers; aggregate results."""
    # Prime chromedriver once to avoid WinError 32
    try:
        ensure_driver_binary_ready()
    except Exception:
        pass

    indexed = list(enumerate(items, start=1))
    shards = _chunk_evenly(indexed, workers)
    stop_event = threading.Event()
    commit_lock = threading.Lock()

    # Don’t let all workers hit SSO at once. If SAP/IdP allows more, raise this.
    login_sem = threading.BoundedSemaphore(int(cfg.get("LOGIN_CONCURRENCY", min(2, workers))))

    all_results: List[Dict[str, Any]] = []

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = []
        for w_id, shard in enumerate(shards, start=1):
            futures.append(pool.submit(_worker_process, shard, stop_event, login_sem, cfg, w_id, commit_lock))

        for fut in as_completed(futures):
            r = fut.result()
            all_results.extend(r.get("results", []))
            if r.get("interrupted"):
                stop_event.set()

    all_results.sort(key=lambda x: x.get("index", 0))

    created = sum(1 for r in all_results if r.get("status") == "created")
    failed = sum(1 for r in all_results if r.get("status") in ("validation_error", "error"))
    skipped = sum(1 for r in all_results if r.get("status") == "skipped")
    interrupted = stop_event.is_set()
    ok = (failed == 0) and (not interrupted)

    return {
        "ok": ok,
        "workers": workers,
        "total": len(items),
        "created": created,
        "failed": failed,
        "skipped": skipped,
        "interrupted_by_dialog": interrupted,
        "results": all_results,
    }


# ------------------- API -------------------

@router.post("/currency/exchange-rates/batch")
async def create_exchange_rates(items: List[ExchangeRateItem]) -> Dict[str, Any]:
    """
    Multi-threaded batch with:
      - Per-thread Chrome profile isolation
      - Watchdog to kill/recover hung browsers
      - Throttled login to avoid SSO throttling
    """
    cfg = config()
    workers = int(cfg.get("NUM_WORKERS", 6)) or 6

    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(None, lambda: _run_multithread(items, workers, cfg))
        return result
    except Exception as e:
        # Never leak a 500 to clients — return a structured error
        return {
            "ok": False,
            "workers": workers,
            "total": len(items),
            "created": 0,
            "failed": len(items),
            "skipped": 0,
            "interrupted_by_dialog": False,
            "error": f"batch_failed: {type(e).__name__}: {e}",
            "results": [],
        }
