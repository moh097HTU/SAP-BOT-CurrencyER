import time
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from selenium.common.exceptions import TimeoutException, StaleElementReferenceException
from core.base import Element
from .selectors import OBJECT_HEADER_CONTENT_XPATH, OBJECT_HEADER_RATE_VALUE_XPATH

class ObjectHeaderVerifier(Element):
    def wait_ready(self, timeout: int) -> bool:
        t0 = time.time()
        try:
            WebDriverWait(self.driver, min(6, timeout), ignored_exceptions=(StaleElementReferenceException,)).until(
                EC.presence_of_element_located((By.XPATH, OBJECT_HEADER_CONTENT_XPATH))
            )
        except TimeoutException:
            return False
        while time.time() - t0 < min(timeout, 10):
            try:
                span = self.driver.find_element(By.XPATH, OBJECT_HEADER_RATE_VALUE_XPATH)
                txt = ""
                try:
                    txt = (span.text or "").strip()
                except StaleElementReferenceException:
                    continue
                if txt:
                    return True
            except Exception:
                pass
            time.sleep(0.15)
        return False
