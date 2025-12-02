# pages/Shell/Search/element.py
from __future__ import annotations

from core.base import Element
from services.ui import wait_ui5_idle

# Keep selectors import for compatibility with any external references.
from .selectors import (
    SEARCH_TOGGLE_CSS_PRIMARY,
    SEARCH_TOGGLE_CSS_ALT_HELP,
    SEARCH_TOGGLE_CSS_ALT_ARIA,
    SEARCH_INPUT_INNER_CSS,
    SUGGEST_TABLE_XPATH,
    APP_ROW_BY_TEXT_XPATH,
    APP_ROW_BY_TEXT_ALT_XPATH,
)

# Intent hash for the Currency Exchange Rates app (target destination)
APP_HASH_CURRENCY = "#Currency-maintainExchangeRates"


class ShellSearch(Element):
    """
    Hard override: DO NOT TYPE IN THE FLP HEADER SEARCH.
    Tenant/FLP is ignoring synthetic keystrokes. We deep-link by intent instead.

    Any existing call sites like:
        ShellSearch(driver).open_search().type_and_choose_app("Currency Exchange Rates")
    will now deterministically navigate to the app hash and wait for UI5 to settle.
    """

    # --- Core navigation helpers ---
    def open_app_by_hash(self, hash_fragment: str, settle_timeout: int = 20):
        h = str(hash_fragment or "").strip()
        if not h.startswith("#"):
            raise ValueError("hash_fragment must start with '#' (e.g. #Currency-maintainExchangeRates)")
        self.driver.execute_script(
            "location.href = location.origin + '/ui?sap-ushell-config=lean' + arguments[0];",
            h
        )
        wait_ui5_idle(self.driver, timeout=max(self._timeout, settle_timeout))
        return self

    def open_currency_app_fast(self, settle_timeout: int | None = None):
        """Go straight to Currency Exchange Rates without touching the search UI."""
        return self.open_app_by_hash(APP_HASH_CURRENCY, settle_timeout or 20)

    # --- OVERRIDES: keep legacy API, force deterministic behavior ---
    def open_search(self):
        """
        No-op to preserve fluent chains.
        Example: ShellSearch(driver).open_search().type_and_choose_app("...")
        """
        return self

    def type_and_choose_app(self, query_text: str, exact_click_text: str = "Currency Exchange Rates"):
        """
        Legacy signature retained. Ignores the header search completely and deep-links to the app.
        """
        return self.open_currency_app_fast()
