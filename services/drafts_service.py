# services/drafts_service.py
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Dict, Any

from services.config import config
from services.driver import get_driver
from services.auth import login
from services.ui import wait_for_shell_home, wait_ui5_idle
from pages.Shell.Search.element import ShellSearch
from pages.CurrencyExchangeRates.page import CurrencyExchangeRatesPage
from pages.CurrencyExchangeRates.elements.DraftFinder import DraftFinder

log = logging.getLogger("sapbot")


def _ddmmyyyy(d: date) -> str:
    return f"{d.day:02d}.{d.month:02d}.{d.year:04d}"


def _daterange_inclusive(d0: date, d1: date):
    cur = d0
    while cur <= d1:
        yield cur
        cur += timedelta(days=1)


def run_delete_drafts_range(day_from: date, day_to: date) -> Dict[str, Any]:
    """
    For each day in [day_from, day_to]:
      - open 'Currency Exchange Rates' app
      - set filter 'Exchange Rate Effective Date' to DD.MM.YYYY and press Enter
      - (optionally pre-scroll) to trigger row rendering
      - delete all currently visible draft rows (one-by-one)
    Returns:
      {
        "ok": bool,
        "days_processed": int,
        "total_deleted": int,
        "per_day": [
          {
            "date": "YYYY-MM-DD",
            "deleted": int,
            "attempts": int,
            "sample": [ "<from->to @ date>", ... ],  # <= up to 10 items if your DraftFinder returns it
            "ok": bool,
            "why": "reason-if-any"
          },
          ...
        ],
        "error": "...optional..."
      }
    """
    cfg = config()
    drv = None
    summary: Dict[str, Any] = {
        "ok": False,
        "days_processed": 0,
        "total_deleted": 0,
        "per_day": [],
    }

    try:
        # Start browser + login + shell
        drv = get_driver(headless=cfg["HEADLESS"])
        login(drv)
        wait_for_shell_home(drv, timeout=cfg["EXPLICIT_WAIT_SECONDS"])
        wait_ui5_idle(drv, timeout=cfg["EXPLICIT_WAIT_SECONDS"])

        # Navigate to app
        ShellSearch(drv).open_search().type_and_choose_app("Currency Exchange Rates")
        wait_ui5_idle(drv, timeout=30)
        CurrencyExchangeRatesPage(drv).ensure_in_app(max_attempts=3, settle_each=8)

        # Normalize range order
        df = min(day_from, day_to)
        dt = max(day_from, day_to)

        total_deleted = 0
        days_count = 0
        per_day_stats = []

        finder = DraftFinder(drv)

        for day in _daterange_inclusive(df, dt):
            days_count += 1
            day_iso = str(day)          # YYYY-MM-DD for API consumers/logs
            date_str = _ddmmyyyy(day)   # DD.MM.YYYY for UI filter

            # Set date and apply
            ok = finder.set_effective_date_and_apply(date_str, timeout=20)
            if not ok:
                per_day_stats.append({
                    "date": day_iso,
                    "deleted": 0,
                    "attempts": 0,
                    "sample": [],
                    "ok": False,
                    "why": "date_set_failed"
                })
                continue

            # Light pre-scroll to help initial rows render
            finder.pre_scroll(times=2, settle=0.5)

            # Delete visible drafts
            sample: list[str] = []
            try:
                # Prefer new triple-return signature if you added it:
                #   deleted, attempts, sample = finder.delete_visible_drafts(...)
                res = finder.delete_visible_drafts(per_click_timeout=16)
                if isinstance(res, (list, tuple)) and len(res) >= 3:
                    deleted, attempts, sample = res[0], res[1], list(res[2])[:10]
                else:
                    # Backward compatibility with (deleted, attempts)
                    deleted, attempts = res  # type: ignore[misc]
                    sample = []
            except Exception as e:
                log.error("[drafts] delete_visible_drafts failed for %s: %s: %s",
                          day_iso, type(e).__name__, e)
                per_day_stats.append({
                    "date": day_iso,
                    "deleted": 0,
                    "attempts": 0,
                    "sample": [],
                    "ok": False,
                    "why": f"delete_failed:{type(e).__name__}"
                })
                continue

            total_deleted += int(deleted)
            per_day_stats.append({
                "date": day_iso,
                "deleted": int(deleted),
                "attempts": int(attempts),
                "sample": sample or [],
                "ok": True
            })

        summary.update(
            ok=True,
            days_processed=days_count,
            total_deleted=total_deleted,
            per_day=per_day_stats,
        )
        return summary

    except Exception as e:
        log.exception("[drafts] deletion run failed")
        summary["error"] = f"{type(e).__name__}: {e}"
        return summary
    finally:
        try:
            if drv and not cfg.get("KEEP_BROWSER"):
                drv.quit()
        except Exception:
            pass
