from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Tuple

from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from services.config import config

def fluent_wait(driver: WebDriver, timeout: float, poll: float = 0.25, ignored_exceptions: tuple = ()):
    """
    Thin helper for Selenium's fluent wait (custom poll interval + ignored exceptions).
    """
    return WebDriverWait(driver, timeout, poll_frequency=poll, ignored_exceptions=ignored_exceptions)

def _all_frames(driver: WebDriver):
    try:
            return driver.find_elements(By.CSS_SELECTOR, "iframe, frame")
    except Exception:
        return []

def _scan_frames_for(driver: WebDriver, locator: Tuple[str, str], timeout: int):
    """
    Fast path: look in default content first (with a very short wait).
    Only then peek into iframes with a tiny per-frame cap.
    """
    # 1) Default content (quick)
    driver.switch_to.default_content()
    try:
        return WebDriverWait(driver, min(3, timeout)).until(
            EC.presence_of_element_located(locator)
        )
    except Exception:
        pass

    # 2) Light iframe sweep (FLP typically doesn't need this)
    frames = _all_frames(driver)
    per_frame = 1.5  # seconds max per frame
    for f in frames:
        try:
            driver.switch_to.default_content()
            driver.switch_to.frame(f)
            el = WebDriverWait(driver, per_frame).until(
                EC.presence_of_element_located(locator)
            )
            return el
        except Exception:
            continue

    driver.switch_to.default_content()
    raise TimeoutError(f"Element not found for {locator}")

@dataclass
class Element:
    driver: WebDriver
    timeout: Optional[int] = None

    def __post_init__(self):
        if self.timeout is None:
            try:
                self.timeout = config()["EXPLICIT_WAIT_SECONDS"]
            except Exception:
                self.timeout = 30

    @property
    def _timeout(self) -> int:
        return self.timeout or config()["EXPLICIT_WAIT_SECONDS"]

    def find(self, by: By, value: str):
        return _scan_frames_for(self.driver, (by, value), self._timeout)

    def wait_visible(self, by: By, value: str):
        el = _scan_frames_for(self.driver, (by, value), self._timeout)
        return WebDriverWait(self.driver, self._timeout).until(EC.visibility_of(el))

    def wait_clickable(self, by: By, value: str):
        _ = _scan_frames_for(self.driver, (by, value), self._timeout)
        return WebDriverWait(self.driver, self._timeout).until(EC.element_to_be_clickable((by, value)))

    def js_click(self, el) -> None:
        self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
        self.driver.execute_script("arguments[0].click();", el)

class Page:
    def __init__(self, driver: WebDriver, root: Optional[str] = None):
        self.driver = driver
        self.root = root

    def open(self, url: str):
        if self.root and not url.lower().startswith(("http://", "https://")):
            url = self.root.rstrip("/") + "/" + url.lstrip("/")
        self.driver.get(url)

    def ensure_url_contains(self, needle: str, timeout: Optional[int] = None):
        t = timeout or config()["EXPLICIT_WAIT_SECONDS"]
        WebDriverWait(self.driver, t).until(
            lambda d: needle.lower() in (d.current_url or "").lower()
        )
