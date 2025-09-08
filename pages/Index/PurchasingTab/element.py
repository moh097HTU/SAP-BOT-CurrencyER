from selenium.webdriver.common.by import By
from core.base import Element
from services.ui import wait_ui5_idle
from .selectors import PURCHASING_TAB_XPATH

class PurchasingTab(Element):
    def click(self):
        wait_ui5_idle(self.driver, timeout=self._timeout)
        el = self.wait_clickable(By.XPATH, PURCHASING_TAB_XPATH)
        try:
            self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
            el.click()
        except Exception:
            self.js_click(el)
