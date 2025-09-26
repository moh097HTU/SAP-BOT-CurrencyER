# services/worker.py
from __future__ import annotations

import logging
import threading
import time
from typing import Dict, Any, List, Tuple

from selenium.common.exceptions import (
    InvalidSessionIdException,
    WebDriverException,
    NoSuchWindowException,
    TimeoutException,
    StaleElementReferenceException,
    ElementClickInterceptedException,
    ElementNotInteractableException,
)

from services.schemas import ExchangeRateItem
from services.driver import get_driver
from services.auth import login
from services.ui import wait_ui5_idle, wait_for_shell_home, wait_shell_search_ready, wait_url_contains
from pages.Shell.Search.element import ShellSearch
from pages.CurrencyExchangeRates.page import CurrencyExchangeRatesPage
from services.commit import commit_gate
from services.tracking import mark_item_status, iter_pending_items

log = logging.getLogger("sapbot")


def _is_fatal_session_err(err: Exception) -> bool:
    msg = (str(err) or "").lower()
    return (
        isinstance(err, (InvalidSessionIdException, NoSuchWindowException))
        or any(s in msg for s in [
            "invalid session id",
            "chrome not reachable",
            "target closed",
            "disconnected: not connected to devtools",
            "cannot determine loading status",
        ])
    )


def _open_currency_app(drv) -> CurrencyExchangeRatesPage:
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


def chunk_evenly(indexed: List[Tuple[int, ExchangeRateItem]], workers: int) -> List[List[Tuple[int, ExchangeRateItem]]]:
    n = max(1, min(workers, len(indexed))) if indexed else 1
    k, m = divmod(len(indexed), n)
    chunks: List[List[Tuple[int, ExchangeRateItem]]] = []
    start = 0
    for i in range(n):
        end = start + k + (1 if i < m else 0)
        if start < end:
            chunks.append(indexed[start:end])
        start = end
    return chunks


def worker_process(
    shard: List[Tuple[int, ExchangeRateItem]],
    stop_event: threading.Event,
    login_sem: threading.Semaphore,
    cfg: Dict[str, Any],
    worker_id: int,
    track_file_path,  # Path
) -> Dict[str, Any]:
    """
    Per-thread worker. Own Chrome session.
    Uses per-worker tracking file to persist progress. Status values:
      - Pending  → not finished, will be retried
      - Done     → created (success)
      - Skipped  → duplicate existed (policy)
      - Error    → terminal error for this batch
    """
    results: List[Dict[str, Any]] = []
    drv = None
    page = None

    WATCHDOG_SECONDS = int(cfg.get("WATCHDOG_SECONDS", 2000))
    MAX_OPEN_RETRIES = 3
    NONFATAL_RETRIES = 2  # soft retries inside SAME driver for flaky DOM

    # Build the pending queue from tracking (preferred) or from shard
    if track_file_path and track_file_path.exists():
        pending_list = iter_pending_items(track_file_path)
        if not pending_list:
            pending_list = shard[:]  # nothing pending, but keep structure
    else:
        pending_list = shard[:]

    def _kill_driver():
        nonlocal drv
        try:
            if drv:
                drv.quit()
        except Exception:
            pass
        drv = None

    def _recreate_driver_and_reopen(max_open_retries: int = MAX_OPEN_RETRIES):
        nonlocal drv, page
        log.warning("[reopen] worker=%s recreating driver (max_open_retries=%s)", worker_id, max_open_retries)
        _kill_driver()
        drv = get_driver(headless=cfg["HEADLESS"])
        with login_sem:
            login(drv)
        wait_ui5_idle(drv, timeout=30)
        last_exc = None
        for attempt in range(1, max_open_retries + 1):
            try:
                page_local = _open_currency_app(drv)
                log.info("[reopen] worker=%s reopened app on attempt=%s", worker_id, attempt)
                return page_local
            except Exception as e:
                last_exc = e
                log.error("[reopen] worker=%s attempt=%s failed: %s: %s", worker_id, attempt, type(e).__name__, e)
                time.sleep(1.0 * attempt)
        raise RuntimeError(f"open_app_failed after {max_open_retries} attempts: {last_exc}")

    def _track_skipped(idx: int, row: Dict[str, Any]):
        """
        Ensure dialog_text (or error) is persisted for Skipped rows, both in results and tracking.
        """
        # normalize & keep dialog_text in results
        if not row.get("dialog_text"):
            # sometimes the page may put the message in 'error'
            if row.get("error"):
                row["dialog_text"] = row["error"]
        results.append(row)
        if track_file_path:
            mark_item_status(
                track_file_path,
                idx,
                "Skipped",
                {
                    "notes": row.get("notes", {}),
                    "dialog_text": row.get("dialog_text") or "",
                },
            )

    try:
        try:
            page = _recreate_driver_and_reopen()
        except Exception as e:
            # Could not open a browser/app now. Leave rows Pending so the runner requeues.
            log.error("[init-failed] worker=%s could not open driver/app: %s: %s",
                      worker_id, type(e).__name__, e)
            return {"interrupted": False, "results": []}

        for idx, it in pending_list:
            if stop_event.is_set():
                stop_event.clear()

            def _watchdog_kill():
                log.critical("[watchdog] worker=%s idx=%s exceeded=%ss → killing driver", worker_id, idx, WATCHDOG_SECONDS)
                _kill_driver()

            def _do_one():
                timer = threading.Timer(WATCHDOG_SECONDS, _watchdog_kill)
                timer.daemon = True
                timer.start()
                try:
                    return page.create_rate(
                        exch_type=it.ExchangeRateType,
                        from_ccy=it.FromCurrency,
                        to_ccy=it.ToCurrency,
                        valid_from_mmddyyyy=it.ValidFrom,
                        quotation=it.Quotation,
                        rate_value=it.ExchangeRate,
                        commit_gate=commit_gate,
                    )
                finally:
                    try:
                        timer.cancel()
                    except Exception:
                        pass

            soft_attempt = 0
            while True:
                try:
                    res = _do_one()
                    row = {"index": idx, "payload": it.dict(), **res, "worker": worker_id}
                    # normalize status coming from page
                    st = (row.get("status") or "").strip().lower()
                    if st == "created":
                        results.append(row)
                        if track_file_path:
                            mark_item_status(track_file_path, idx, "Done", {"notes": row.get("notes", {})})
                    elif st == "skipped":
                        _track_skipped(idx, row)
                    elif st == "pending":
                        results.append(row)
                        if track_file_path:
                            mark_item_status(track_file_path, idx, "Pending", {"notes": row.get("notes", {})})
                    else:
                        results.append({**row, "status": "error"})
                        if track_file_path:
                            mark_item_status(track_file_path, idx, "Error",
                                             {"error": row.get("error") | row.get("dialog_text") if isinstance(row.get("error"), str) else (row.get("dialog_text") or "")})
                    time.sleep(0.2)
                    break

                except TimeoutException as e:
                    log.error("[driver-recreate] worker=%s idx=%s cause=TimeoutException msg=%r", worker_id, idx, str(e))
                    try:
                        page = _recreate_driver_and_reopen(max_open_retries=2)
                        res = _do_one()
                        row = {"index": idx, "payload": it.dict(), **res, "worker": worker_id}
                        st = (row.get("status") or "").strip().lower()
                        if st == "created":
                            results.append(row); mark_item_status(track_file_path, idx, "Done", {"notes": row.get("notes", {})})
                        elif st == "skipped":
                            _track_skipped(idx, row)
                        elif st == "pending":
                            results.append(row); mark_item_status(track_file_path, idx, "Pending", {"notes": row.get("notes", {})})
                        else:
                            results.append({**row, "status": "error"}); mark_item_status(track_file_path, idx, "Error",
                                                                                          {"error": row.get("error") or row.get("dialog_text") or ""})
                    except Exception as e2:
                        row = {
                            "index": idx, "payload": it.dict(), "status": "error",
                            "error": f"recover_failed(w{worker_id}): {type(e2).__name__}: {e2}",
                            "worker": worker_id,
                        }
                        results.append(row)
                        if track_file_path:
                            mark_item_status(track_file_path, idx, "Error", {"error": row["error"]})
                    break

                except (StaleElementReferenceException, ElementClickInterceptedException, ElementNotInteractableException) as e:
                    if soft_attempt < NONFATAL_RETRIES:
                        soft_attempt += 1
                        log.warning("[soft-retry] worker=%s idx=%s attempt=%s cls=%s msg=%r",
                                    worker_id, idx, soft_attempt, type(e).__name__, str(e))
                        try:
                            page.ensure_in_app_quick()
                        except Exception:
                            try:
                                page.ensure_in_app(max_attempts=2, settle_each=8)
                            except Exception:
                                pass
                        time.sleep(0.3)
                        continue
                    else:
                        log.error("[soft-retry-exhausted] worker=%s idx=%s cls=%s → recreating driver",
                                  worker_id, idx, type(e).__name__)
                        try:
                            page = _recreate_driver_and_reopen(max_open_retries=2)
                            res = _do_one()
                            row = {"index": idx, "payload": it.dict(), **res, "worker": worker_id}
                            st = (row.get("status") or "").strip().lower()
                            if st == "created":
                                results.append(row); mark_item_status(track_file_path, idx, "Done", {"notes": row.get("notes", {})})
                            elif st == "skipped":
                                _track_skipped(idx, row)
                            elif st == "pending":
                                results.append(row); mark_item_status(track_file_path, idx, "Pending", {"notes": row.get("notes", {})})
                            else:
                                results.append({**row, "status": "error"}); mark_item_status(track_file_path, idx, "Error",
                                                                                              {"error": row.get("error") or row.get("dialog_text") or ""})
                        except Exception as e2:
                            row = {
                                "index": idx, "payload": it.dict(), "status": "error",
                                "error": f"recover_failed(w{worker_id}): {type(e2).__name__}: {e2}",
                                "worker": worker_id,
                            }
                            results.append(row)
                            if track_file_path:
                                mark_item_status(track_file_path, idx, "Error", {"error": row["error"]})
                        break

                except WebDriverException as e:
                    fatal = _is_fatal_session_err(e)
                    log.error("[driver-exc] worker=%s idx=%s fatal=%s cls=%s msg=%r",
                              worker_id, idx, fatal, type(e).__name__, str(e))
                    if fatal:
                        try:
                            page = _recreate_driver_and_reopen(max_open_retries=2)
                            res = _do_one()
                            row = {"index": idx, "payload": it.dict(), **res, "worker": worker_id}
                            st = (row.get("status") or "").strip().lower()
                            if st == "created":
                                results.append(row); mark_item_status(track_file_path, idx, "Done", {"notes": row.get("notes", {})})
                            elif st == "skipped":
                                _track_skipped(idx, row)
                            elif st == "pending":
                                results.append(row); mark_item_status(track_file_path, idx, "Pending", {"notes": row.get("notes", {})})
                            else:
                                results.append({**row, "status": "error"}); mark_item_status(track_file_path, idx, "Error",
                                                                                              {"error": row.get("error") or row.get("dialog_text") or ""})
                        except Exception as e2:
                            row = {
                                "index": idx, "payload": it.dict(), "status": "error",
                                "error": f"recover_failed(w{worker_id}): {type(e2).__name__}: {e2}",
                                "worker": worker_id,
                            }
                            results.append(row)
                            if track_file_path:
                                mark_item_status(track_file_path, idx, "Error", {"error": row["error"]})
                    else:
                        if soft_attempt < NONFATAL_RETRIES:
                            soft_attempt += 1
                            log.warning("[soft-retry] worker=%s idx=%s attempt=%s nonfatal-webdriver cls=%s msg=%r",
                                        worker_id, idx, soft_attempt, type(e).__name__, str(e))
                            try:
                                page.ensure_in_app_quick()
                            except Exception:
                                try:
                                    page.ensure_in_app(max_attempts=2, settle_each=8)
                                except Exception:
                                    pass
                            time.sleep(0.3)
                            continue
                        else:
                            log.error("[soft-retry-exhausted] worker=%s idx=%s nonfatal-webdriver → recreating driver",
                                      worker_id, idx)
                            try:
                                page = _recreate_driver_and_reopen(max_open_retries=2)
                                res = _do_one()
                                row = {"index": idx, "payload": it.dict(), **res, "worker": worker_id}
                                st = (row.get("status") or "").strip().lower()
                                if st == "created":
                                    results.append(row); mark_item_status(track_file_path, idx, "Done", {"notes": row.get("notes", {})})
                                elif st == "skipped":
                                    _track_skipped(idx, row)
                                elif st == "pending":
                                    results.append(row); mark_item_status(track_file_path, idx, "Pending", {"notes": row.get("notes", {})})
                                else:
                                    results.append({**row, "status": "error"}); mark_item_status(track_file_path, idx, "Error",
                                                                                                {"error": row.get("error") or row.get("dialog_text") or ""})
                            except Exception as e2:
                                row = {
                                    "index": idx, "payload": it.dict(), "status": "error",
                                    "error": f"recover_failed(w{worker_id}): {type(e2).__name__}: {e2}",
                                    "worker": worker_id,
                                }
                                results.append(row)
                                if track_file_path:
                                    mark_item_status(track_file_path, idx, "Error", {"error": row["error"]})
                    break

    finally:
        try:
            if drv:
                drv.quit()
        except Exception:
            pass

    return {"interrupted": False, "results": results}
