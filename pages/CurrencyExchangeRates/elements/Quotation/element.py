from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import StaleElementReferenceException
import time

from core.base import Element
from services.ui import wait_ui5_idle
from .selectors import QUOTATION_INNER_INPUT_XPATH, QUOTATION_ARROW_BTN_XPATH, QUOTATION_OPTION_BY_TEXT_XPATH

def _retry_stale(fn, tries=3, pause=0.12):
    last = None
    for _ in range(max(1, tries)):
        try:
            return fn()
        except StaleElementReferenceException as e:
            last = e
            time.sleep(pause)
    if last:
        raise last
    return None

class QuotationField(Element):
    def _hard_clear(self, inp):
        for fn in (
            lambda: inp.clear(),
            lambda: inp.send_keys(Keys.CONTROL, "a"),
            lambda: inp.send_keys(Keys.DELETE),
            lambda: self.driver.execute_script(
                "arguments[0].value='';"
                "arguments[0].dispatchEvent(new Event('input',{bubbles:true}));"
                "arguments[0].dispatchEvent(new Event('change',{bubbles:true}));", inp),
        ):
            try: _retry_stale(fn)
            except Exception: pass

    def set_value(self, value: str):
        wait = WebDriverWait(self.driver, max(self._timeout, 20), ignored_exceptions=(StaleElementReferenceException,))
        inp = wait.until(EC.visibility_of_element_located((By.XPATH, QUOTATION_INNER_INPUT_XPATH)))

        try: _retry_stale(lambda: inp.click())
        except Exception: self.js_click(inp)

        self._hard_clear(inp)

        _retry_stale(lambda: inp.send_keys(value))
        _retry_stale(lambda: inp.send_keys(Keys.ENTER))
        _retry_stale(lambda: inp.send_keys(Keys.TAB))
        wait_ui5_idle(self.driver, timeout=min(self._timeout, 4))

        def _cur():
            return (inp.get_attribute("value") or "").strip()
        try:
            cur = _retry_stale(_cur)
        except Exception:
            cur = ""
        if cur.lower() != value.strip().lower():
            try:
                arrow = wait.until(EC.element_to_be_clickable((By.XPATH, QUOTATION_ARROW_BTN_XPATH)))
                try: _retry_stale(lambda: arrow.click())
                except Exception: self.js_click(arrow)
            except Exception:
                try: _retry_stale(lambda: inp.send_keys(Keys.ALT, Keys.DOWN))
                except Exception: pass
            wait_ui5_idle(self.driver, timeout=min(self._timeout, 4))
            opt_xpath = QUOTATION_OPTION_BY_TEXT_XPATH.format(TEXT=value.strip())
            option = wait.until(EC.element_to_be_clickable((By.XPATH, opt_xpath)))
            try: _retry_stale(lambda: option.click())
            except Exception: self.js_click(option)
            wait_ui5_idle(self.driver, timeout=min(self._timeout, 4))
