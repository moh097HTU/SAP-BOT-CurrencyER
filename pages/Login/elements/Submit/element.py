from selenium.webdriver.common.by import By
from core.base import Element
from .selectors import SUBMIT_BTN

class Submit(Element):
    def click(self):
        el = self.wait_clickable(By.CSS_SELECTOR, SUBMIT_BTN)
        try:
            el.click()
        except Exception:
            self.js_click(el)
