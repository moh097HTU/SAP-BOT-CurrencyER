from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import StaleElementReferenceException
import time

from core.base import Element
from services.ui import wait_ui5_idle
from .selectors import (
    EXCH_TYPE_INPUT_XPATH,
    FROM_CCY_INPUT_XPATH,
    TO_CCY_INPUT_XPATH,
    VALID_FROM_INPUT_XPATH,
)

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

class Fields(Element):
    EXCH_TYPE_INPUT_XPATH = ("//input[contains(@id,'ExchangeRateTypeForEdit::Field-input-inner')]")
    FROM_CCY_INPUT_XPATH  = ("//input[contains(@id,'SourceCurrencyForEdit::Field-input-inner')]")
    TO_CCY_INPUT_XPATH    = ("//input[contains(@id,'TargetCurrencyForEdit::Field-input-inner')]")
    VALID_FROM_INPUT_XPATH= ("//input[contains(@id,'ExchangeRateEffectiveDateFoEd::Field-datePicker-inner')]")

    def _hard_clear(self, web_el):
        for fn in (
            lambda: web_el.clear(),
            lambda: web_el.send_keys(Keys.CONTROL, "a"),
            lambda: web_el.send_keys(Keys.DELETE),
            lambda: self.driver.execute_script(
                "arguments[0].value='';"
                "arguments[0].dispatchEvent(new Event('input',{bubbles:true}));"
                "arguments[0].dispatchEvent(new Event('change',{bubbles:true}));", web_el),
        ):
            try: _retry_stale(fn)
            except Exception: pass

    def get_input_value(self, xpath: str) -> str:
        def _get():
            el = self.find(By.XPATH, xpath)
            return el.get_attribute("value") or ""
        try:
            return _retry_stale(_get)
        except Exception:
            return ""

    def set_plain_input(self, xpath: str, text: str, press_enter: bool = False) -> None:
        def _get():
            return self.wait_clickable(By.XPATH, xpath)
        inp = _retry_stale(_get)

        def _focus_click():
            try:
                self.js_click(inp)
            except Exception:
                inp.click()
        _retry_stale(_focus_click)

        _retry_stale(lambda: inp.clear())
        _retry_stale(lambda: inp.send_keys(str(text or "")))
        if press_enter:
            _retry_stale(lambda: inp.send_keys(Keys.ENTER))
        try:
            self.driver.execute_script(
                "arguments[0].dispatchEvent(new Event('change',{bubbles:true})); arguments[0].blur && arguments[0].blur();",
                inp
            )
        except Exception:
            pass
        # tiny settle helps UI5 bindings stabilize before subsequent reads
        wait_ui5_idle(self.driver, timeout=min(self._timeout, 3))
