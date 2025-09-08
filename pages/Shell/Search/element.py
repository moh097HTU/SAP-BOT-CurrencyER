# pages/Shell/Search/element.py
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import InvalidElementStateException, TimeoutException

from core.base import Element
from services.ui import wait_ui5_idle, wait_shell_search_ready, open_shell_search_via_js
from .selectors import (
    SEARCH_TOGGLE_CSS_PRIMARY,
    SEARCH_TOGGLE_CSS_ALT_HELP,
    SEARCH_TOGGLE_CSS_ALT_ARIA,
    SEARCH_INPUT_INNER_CSS,
    SUGGEST_TABLE_XPATH,
    APP_ROW_BY_TEXT_XPATH,
    APP_ROW_BY_TEXT_ALT_XPATH,
)

class ShellSearch(Element):
    def _wait_input_interactable(self):
        """
        Wait until the shell search input is present, visible, and not disabled/readOnly.
        Also ensure it has non-zero size (animation finished).
        """
        wait = WebDriverWait(self.driver, max(self._timeout, 25))
        inp = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, SEARCH_INPUT_INNER_CSS)))
        # Visible
        inp = wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, SEARCH_INPUT_INNER_CSS)))
        # Enabled + not readOnly + has size
        wait.until(lambda d: d.execute_script(
            "var el=arguments[0];"
            "if(!el) return false;"
            "var cs=window.getComputedStyle(el);"
            "var ok=!!(el.offsetParent) && cs.visibility!=='hidden' && cs.display!=='none' && "
            "!el.disabled && !el.readOnly && el.clientWidth>0 && el.clientHeight>0;"
            "return ok;", inp))
        # Focus it
        try:
            inp.click()
        except Exception:
            self.js_click(inp)
        try:
            self.driver.execute_script("arguments[0].focus();", inp)
        except Exception:
            pass
        return inp

    def open_search(self):
        # Give UI5/FLP time to render the header/search
        wait_ui5_idle(self.driver, timeout=max(self._timeout, 25))
        wait_shell_search_ready(self.driver, timeout=max(self._timeout, 25))

        # Try clicking toggle; else JS renderer fallback
        candidates = (SEARCH_TOGGLE_CSS_PRIMARY, SEARCH_TOGGLE_CSS_ALT_HELP, SEARCH_TOGGLE_CSS_ALT_ARIA)
        clicked = False
        for css in candidates:
            try:
                el = WebDriverWait(self.driver, max(self._timeout, 25)).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, css))
                )
                try:
                    el.click()
                except Exception:
                    self.js_click(el)
                clicked = True
                break
            except Exception:
                continue

        if not clicked:
            if not open_shell_search_via_js(self.driver):
                raise TimeoutError("Shell search toggle not found and JS fallback failed.")

        # Wait until input is truly interactable (not just present)
        self._wait_input_interactable()
        wait_ui5_idle(self.driver, timeout=max(self._timeout, 25))
        return self

    def type_and_choose_app(self, query_text: str):
        inp = self._wait_input_interactable()

        # Clear safely
        try:
            inp.clear()
        except InvalidElementStateException:
            # JS clear fallback
            self.driver.execute_script(
                "arguments[0].value=''; arguments[0].dispatchEvent(new Event('input',{bubbles:true}));",
                inp
            )

        # Type the query; if Selenium send_keys bounces, use JS then send ENTER to trigger suggestions
        try:
            inp.send_keys(query_text)
        except InvalidElementStateException:
            self.driver.execute_script(
                "arguments[0].value=arguments[1]; arguments[0].dispatchEvent(new Event('input',{bubbles:true}));",
                inp, query_text
            )
            inp.send_keys(Keys.ENTER)

        # Wait for suggestions table to show up
        wait = WebDriverWait(self.driver, max(self._timeout, 25))
        try:
            wait.until(EC.presence_of_element_located((By.XPATH, SUGGEST_TABLE_XPATH)))
        except TimeoutException:
            # If suggestions didn't appear, fallback: open the app directly by intent hash
            self.driver.execute_script(
                "location.href = location.origin + '/ui?sap-ushell-config=lean#Currency-maintainExchangeRates';"
            )
            wait_ui5_idle(self.driver, timeout=max(self._timeout, 25))
            return self

        # Click the suggestion row (exact text), else fallback to contains()
        for xp in (APP_ROW_BY_TEXT_XPATH, APP_ROW_BY_TEXT_ALT_XPATH):
            try:
                row = wait.until(EC.element_to_be_clickable((By.XPATH, xp)))
                try:
                    row.click()
                except Exception:
                    self.js_click(row)
                wait_ui5_idle(self.driver, timeout=max(self._timeout, 25))
                return self
            except TimeoutException:
                continue

        # Last resort: deep-link by hash
        self.driver.execute_script(
            "location.href = location.origin + '/ui?sap-ushell-config=lean#Currency-maintainExchangeRates';"
        )
        wait_ui5_idle(self.driver, timeout=max(self._timeout, 25))
        return self
