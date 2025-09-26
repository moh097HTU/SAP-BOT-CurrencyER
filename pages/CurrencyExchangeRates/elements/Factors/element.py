from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import StaleElementReferenceException
import time

from core.base import Element
from services.ui import wait_ui5_idle
from .selectors import FROM_FACTOR_BY_LABEL_XPATH, TO_FACTOR_BY_LABEL_XPATH

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

class Factors(Element):
    def _try_set_by_label(self, label_xpath: str, value: str = "1") -> bool:
        def _find():
            return self.driver.find_element(By.XPATH, label_xpath)

        try:
            inp = _retry_stale(_find)
        except Exception:
            return False

        try:
            for fn in (
                lambda: inp.clear(),
                lambda: inp.send_keys(Keys.CONTROL, "a"),
                lambda: inp.send_keys(Keys.DELETE),
                lambda: self.driver.execute_script(
                    "arguments[0].value='';"
                    "arguments[0].dispatchEvent(new Event('input',{bubbles:true}));"
                    "arguments[0].dispatchEvent(new Event('change',{bubbles:true}));", inp),
            ):
                try:
                    _retry_stale(fn)
                except Exception:
                    pass

            _retry_stale(lambda: inp.send_keys(value))
            try: _retry_stale(lambda: inp.send_keys(Keys.TAB))
            except Exception: pass
            wait_ui5_idle(self.driver, timeout=min(self._timeout, 4))
            return True
        except Exception:
            return False

    def try_set_from(self, value: str = "1") -> bool:
        return self._try_set_by_label(FROM_FACTOR_BY_LABEL_XPATH, value)

    def try_set_to(self, value: str = "1") -> bool:
        return self._try_set_by_label(TO_FACTOR_BY_LABEL_XPATH, value)
