from selenium.webdriver.common.by import By
from core.base import Element
from .selectors import USERNAME_INPUT

class Username(Element):
    def set(self, value: str):
        el = self.wait_visible(By.CSS_SELECTOR, USERNAME_INPUT)
        el.clear()
        el.send_keys(value)
