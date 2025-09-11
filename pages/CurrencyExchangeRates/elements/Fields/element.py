from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from core.base import Element
from services.ui import wait_ui5_idle
from .selectors import (
    EXCH_TYPE_INPUT_XPATH,
    FROM_CCY_INPUT_XPATH,
    TO_CCY_INPUT_XPATH,
    VALID_FROM_INPUT_XPATH,
)

class Fields(Element):
    EXCH_TYPE_INPUT_XPATH = EXCH_TYPE_INPUT_XPATH
    FROM_CCY_INPUT_XPATH = FROM_CCY_INPUT_XPATH
    TO_CCY_INPUT_XPATH = TO_CCY_INPUT_XPATH
    VALID_FROM_INPUT_XPATH = VALID_FROM_INPUT_XPATH

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
            try: fn()
            except Exception: pass

    def set_plain_input(self, xpath: str, value: str, press_enter: bool = False):
        inp = self.wait_visible(By.XPATH, xpath)
        self._hard_clear(inp)
        if value is not None:
            inp.send_keys(value)
        if press_enter:
            try: inp.send_keys(Keys.ENTER)
            except Exception: pass
        try: inp.send_keys(Keys.TAB)
        except Exception: pass
        wait_ui5_idle(self.driver, timeout=self._timeout)
