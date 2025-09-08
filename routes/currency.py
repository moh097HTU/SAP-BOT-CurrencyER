# routes/currency.py
from fastapi import APIRouter
from pydantic import BaseModel, Field, validator
from typing import List, Dict, Any, Optional
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime
import time

from selenium.common.exceptions import (
    InvalidSessionIdException,
    WebDriverException,
    NoSuchWindowException,
)

from services.config import config
from services.driver import get_driver
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

class ExchangeRateItem(BaseModel):
    ExchangeRateType: str = Field(..., description="e.g. M")
    FromCurrency: str = Field(..., description="e.g. USD")
    ToCurrency: str = Field(..., description="e.g. JOD")
    ValidFrom: str = Field(..., description="Date like 12/31/2025 or 2025-12-31")
    Quotation: Optional[str] = Field("Direct", description="Direct or Indirect")
    ExchangeRate: str | float | Decimal = Field(..., description="> 0; rounded to 5 dp")

    @validator("ExchangeRateType", "FromCurrency", "ToCurrency")
    def _up(cls, v: str): return (v or "").strip().upper()

    @validator("Quotation", always=True)
    def _q(cls, v: Optional[str]):
        s = (v or "Direct").strip().capitalize()
        return "Indirect" if s.startswith("Ind") else "Direct"

    @validator("ValidFrom")
    def _datefmt(cls, v: str):
        s = (v or "").strip()
        fmts = ["%m/%d/%Y","%Y-%m-%d","%Y/%m/%d","%d/%m/%Y","%Y%m%d"]
        for f in fmts:
            try:
                return datetime.strptime(s, f).strftime("%m/%d/%Y")
            except Exception:
                pass
        raise ValueError(f"Unrecognized date: {v}")

    @validator("ExchangeRate")
    def _5dp(cls, v):
        q = Decimal(str(v))
        if q <= 0: raise ValueError("ExchangeRate must be > 0")
        q = q.quantize(Decimal("0.00001"), rounding=ROUND_HALF_UP)
        return f"{q:.5f}"


def _open_currency_app(drv) -> CurrencyExchangeRatesPage:
    """Open FLP → Global Search → Currency Exchange Rates app, return page object."""
    cfg = config()
    if not wait_for_shell_home(drv, timeout=40):
        raise RuntimeError("Shell home not detected after login")
    wait_ui5_idle(drv, timeout=30)
    wait_shell_search_ready(drv, timeout=30)

    ShellSearch(drv).open_search().type_and_choose_app("Currency Exchange Rates")
    wait_ui5_idle(drv, timeout=30)
    wait_url_contains(drv, "#Currency-maintainExchangeRates", 30)

    page = CurrencyExchangeRatesPage(drv)
    page.ensure_in_app()
    return page


def _is_fatal_session_err(err: Exception) -> bool:
    msg = (str(err) or "").lower()
    return isinstance(err, (InvalidSessionIdException, NoSuchWindowException)) or any(
        s in msg for s in [
            "invalid session id",
            "chrome not reachable",
            "target closed",
            "disconnected: not connected to devtools",
            "cannot determine loading status",
        ]
    )


@router.post("/currency/exchange-rates/batch")
async def create_exchange_rates(items: List[ExchangeRateItem]) -> Dict[str, Any]:
    cfg = config()
    drv = get_driver(headless=cfg["HEADLESS"])
    results: List[Dict[str, Any]] = []

    def _recreate_driver_and_reopen():
        nonlocal drv, page
        try:
            drv.quit()
        except Exception:
            pass
        drv = get_driver(headless=cfg["HEADLESS"])
        login(drv)
        wait_ui5_idle(drv, timeout=30)
        return _open_currency_app(drv)

    try:
        # initial login + open app
        login(drv)
        page = _open_currency_app(drv)

        for idx, it in enumerate(items, start=1):
            attempt = 0
            while True:
                try:
                    res = page.create_rate(
                        exch_type=it.ExchangeRateType,
                        from_ccy=it.FromCurrency,
                        to_ccy=it.ToCurrency,
                        valid_from_mmddyyyy=it.ValidFrom,
                        quotation=it.Quotation,
                        rate_value=it.ExchangeRate
                    )
                    results.append({"index": idx, "payload": it.dict(), **res})

                    # if a dialog popped up, stop early and return so user can read it
                    if res.get("status") == "dialog_open":
                        return {
                            "ok": False,
                            "interrupted_by_dialog": True,
                            "message": "A dialog is open. Leaving it visible for you to read.",
                            "result": results[-1],
                            "results_so_far": results
                        }

                    # page.create_rate already returns to list on success; tiny settle
                    time.sleep(0.3)
                    break

                except WebDriverException as e:
                    if _is_fatal_session_err(e) and attempt == 0:
                        # Recover session once, then retry this same item
                        page = _recreate_driver_and_reopen()
                        attempt += 1
                        continue
                    # unrecoverable or second failure → record and move on
                    results.append({
                        "index": idx,
                        "payload": it.dict(),
                        "status": "error",
                        "error": f"{type(e).__name__}: {e}",
                    })
                    break

        return {
            "ok": all(r.get("status") in ("created","unknown") for r in results),
            "total": len(items),
            "created": sum(1 for r in results if r.get("status") == "created"),
            "failed": sum(1 for r in results if r.get("status") in ("validation_error","error")),
            "results": results
        }
    finally:
        if not cfg.get("KEEP_BROWSER"):
            try:
                drv.quit()
            except Exception:
                pass
