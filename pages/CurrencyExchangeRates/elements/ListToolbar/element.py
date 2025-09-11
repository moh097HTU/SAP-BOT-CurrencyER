from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from core.base import Element, fluent_wait
from services.ui import wait_ui5_idle
from .selectors import CREATE_BUTTON_XPATH

class ListToolbar(Element):
    def wait_create_clickable(self, timeout: int):
        return fluent_wait(self.driver, timeout, poll=0.2).until(
            EC.element_to_be_clickable((By.XPATH, CREATE_BUTTON_XPATH))
        )

    def click_create(self, timeout: int):
        btn = self.wait_create_clickable(timeout)
        try:
            btn.click()
        except Exception:
            self.js_click(btn)
        wait_ui5_idle(self.driver, timeout=timeout)

    def is_at_list(self, quick: float = 0.8) -> bool:
        try:
            fluent_wait(self.driver, quick, poll=0.2).until(
                EC.element_to_be_clickable((By.XPATH, CREATE_BUTTON_XPATH))
            )
            return True
        except Exception:
            return False
