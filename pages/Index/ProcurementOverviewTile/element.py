from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from core.base import Element
from services.ui import wait_ui5_idle
from .selectors import GRID_READY_XPATH, BY_HREF_XPATH, BY_TITLE_TEXT_XPATH, BY_ARIA_LABEL_XPATH

class ProcurementOverviewTile(Element):
    def _find_tile_quick(self, timeout_s: float):
        wait = WebDriverWait(self.driver, timeout_s)
        # Ensure tiles grid exists
        wait.until(EC.presence_of_element_located((By.XPATH, GRID_READY_XPATH)))

        # Try a few reliable selectors with short caps
        for xp in (BY_HREF_XPATH, BY_TITLE_TEXT_XPATH, BY_ARIA_LABEL_XPATH):
            try:
                return WebDriverWait(self.driver, timeout_s).until(
                    EC.presence_of_element_located((By.XPATH, xp))
                )
            except Exception:
                continue
        return None

    def click(self):
        # Keep things brisk
        short = min(self._timeout, 6)
        wait_ui5_idle(self.driver, timeout=short)

        el = self._find_tile_quick(timeout_s=short)
        if el:
            href = (el.get_attribute("href") or "").strip()
            # Try normal click → JS click
            try:
                self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
                WebDriverWait(self.driver, short).until(EC.element_to_be_clickable((By.XPATH, BY_TITLE_TEXT_XPATH)))
                el.click()
                wait_ui5_idle(self.driver, timeout=short)
                return
            except Exception:
                try:
                    self.driver.execute_script("arguments[0].click();", el)
                    wait_ui5_idle(self.driver, timeout=short)
                    return
                except Exception:
                    if href:
                        self.driver.execute_script("window.location.href = arguments[0];", href)
                        wait_ui5_idle(self.driver, timeout=self._timeout)
                        return
                    raise RuntimeError("Found tile but could not activate it.")
        else:
            # Hard fallback: navigate directly by hash (fastest)
            self.driver.execute_script(
                "location.href = location.origin + '/ui?sap-ushell-config=lean#Procurement-displayOverviewPage';"
            )
            wait_ui5_idle(self.driver, timeout=self._timeout)
