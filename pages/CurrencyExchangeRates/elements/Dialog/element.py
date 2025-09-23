from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from core.base import Element
from .selectors import DIALOG_ROOT_CSS

_PRIMARY_BTN_XPATH = (
    "(.//bdi[normalize-space()='OK']/ancestor::button[1]"
    " | .//bdi[normalize-space()='Close']/ancestor::button[1]"
    " | .//bdi[normalize-space()='Cancel']/ancestor::button[1]"
    " | .//button[@type='button' and not(@disabled)])[1]"
)
_CLOSE_ICON_XPATH = ".//button[contains(@class,'sapMDialogClose')]"

class DialogWatcher(Element):
    def _visible_dialog_el(self):
        try:
            nodes = self.driver.find_elements(By.CSS_SELECTOR, DIALOG_ROOT_CSS)
            for el in reversed(nodes):
                if not el:
                    continue
                try:
                    if el.is_displayed() and el.size.get("width", 0) > 0 and el.size.get("height", 0) > 0:
                        return el
                except Exception:
                    continue
        except Exception:
            pass
        return None

    def is_open(self) -> bool:
        return self._visible_dialog_el() is not None

    def text(self) -> str:
        try:
            el = self._visible_dialog_el()
            if not el:
                return ""
            return (el.text or "").strip()
        except Exception:
            return ""

    def close(self, timeout: float = 2.0) -> bool:
        """
        Best-effort: click Close/OK/Cancel; else X icon.
        Returns True if we think it was closed.
        """
        try:
            el = self._visible_dialog_el()
            if not el:
                return True

            # Try main action button first
            try:
                btn = el.find_element(By.XPATH, _PRIMARY_BTN_XPATH)
                try:
                    btn.click()
                except Exception:
                    self.js_click(btn)
            except Exception:
                # Try close icon
                try:
                    x = el.find_element(By.XPATH, _CLOSE_ICON_XPATH)
                    try:
                        x.click()
                    except Exception:
                        self.js_click(x)
                except Exception:
                    pass

            # Wait until gone
            try:
                WebDriverWait(self.driver, timeout).until_not(
                    EC.visibility_of(el)
                )
            except Exception:
                pass

            return not self.is_open()
        except Exception:
            return False
