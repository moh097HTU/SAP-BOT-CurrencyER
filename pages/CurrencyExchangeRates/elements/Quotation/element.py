from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from core.base import Element
from services.ui import wait_ui5_idle
from .selectors import QUOTATION_INNER_INPUT_XPATH, QUOTATION_ARROW_BTN_XPATH, QUOTATION_OPTION_BY_TEXT_XPATH

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
            try: fn()
            except Exception: pass

    def set_value(self, value: str):
        wait = WebDriverWait(self.driver, max(self._timeout, 20))
        inp = self.wait_visible(By.XPATH, QUOTATION_INNER_INPUT_XPATH)
        try: inp.click()
        except Exception: self.js_click(inp)

        self._hard_clear(inp)

        inp.send_keys(value)
        inp.send_keys(Keys.ENTER)
        inp.send_keys(Keys.TAB)
        wait_ui5_idle(self.driver, timeout=min(self._timeout, 4))

        cur = (inp.get_attribute("value") or "").strip()
        if cur.lower() != value.strip().lower():
            try:
                arrow = wait.until(EC.element_to_be_clickable((By.XPATH, QUOTATION_ARROW_BTN_XPATH)))
                try: arrow.click()
                except Exception: self.js_click(arrow)
            except Exception:
                try: inp.send_keys(Keys.ALT, Keys.DOWN)
                except Exception: pass
            wait_ui5_idle(self.driver, timeout=min(self._timeout, 4))
            opt_xpath = QUOTATION_OPTION_BY_TEXT_XPATH.format(TEXT=value.strip())
            option = wait.until(EC.element_to_be_clickable((By.XPATH, opt_xpath)))
            try: option.click()
            except Exception: self.js_click(option)
            wait_ui5_idle(self.driver, timeout=min(self._timeout, 4))
