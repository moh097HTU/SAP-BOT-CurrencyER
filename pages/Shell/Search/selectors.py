# pages/Shell/Search/selectors.py

# Shell search toggle (try a few stable variants)
SEARCH_TOGGLE_CSS_PRIMARY = "a#sf.sapUshellShellHeadItm"
SEARCH_TOGGLE_CSS_ALT_HELP = "a.sapUshellShellHeadItm[data-help-id='shellHeader-search']"
SEARCH_TOGGLE_CSS_ALT_ARIA = "a.sapUshellShellHeadItm[role='button'][aria-label*='Search']"

# The input that appears after opening search (robust id pattern)
SEARCH_INPUT_INNER_CSS = "input[id*='searchFieldInShell'][id$='-inner']"

# Suggestion table + target row
SUGGEST_TABLE_XPATH = "//table[contains(@id,'searchFieldInShell-input-popup-table-listUl')]"
# Prefer exact text; fall back to contains if localized slightly
APP_ROW_BY_TEXT_XPATH = (
    SUGGEST_TABLE_XPATH +
    "//span[normalize-space()='Currency Exchange Rates']/ancestor::*[self::tr or self::li][1]"
)
APP_ROW_BY_TEXT_ALT_XPATH = (
    SUGGEST_TABLE_XPATH +
    "//span[contains(normalize-space(),'Currency Exchange Rate')]/ancestor::*[self::tr or self::li][1]"
)
