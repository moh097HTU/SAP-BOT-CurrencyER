from selenium.webdriver.common.by import By
from core.base import Element
from .selectors import PASSWORD_INPUT

class Password(Element):
    def set(self, value: str):
        el = self.wait_visible(By.CSS_SELECTOR, PASSWORD_INPUT)
        el.clear()
        el.send_keys(value)
