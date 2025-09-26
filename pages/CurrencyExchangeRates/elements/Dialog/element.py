# pages/CurrencyExchangeRates/elements/Dialog/element.py
from __future__ import annotations

from typing import Optional
import time

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    StaleElementReferenceException,
    NoSuchElementException,
)

from core.base import Element

# Robust selectors for the Message Popover
_POPOVER_WRAPPER_CSS = ".sapMPopoverWrapper"
_POPOVER_CONT_CSS    = ".sapMPopoverCont"
_CLOSE_BTN_CSS       = "button.sapMMsgPopoverCloseBtn"   # the “X” button
# Title/span for message text (works for list view items)
_MSG_ITEM_TITLE_XP   = "//li[contains(@class,'sapMMsgViewItem')]" \
                        "//span[contains(@id,'-titleText')]"

# Generic dialog “Close” button by visible text
_CLOSE_BDI_BTN_XP    = "//bdi[normalize-space()='Close']/ancestor::button[1] | //button[.//bdi[normalize-space()='Close']]"
# Generic OK button (fallbacks)
_OK_BDI_BTN_XP       = "//bdi[normalize-space()='OK']/ancestor::button[1] | //button[.//bdi[normalize-space()='OK']]"

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


class DialogWatcher:
    """
    Handles both classic sap.m.Dialog and the Message Popover.
    Now also knows how to click a <bdi>Close</bdi> button exactly like:
      <span class="sapMBtnContent"><bdi>Close</bdi></span>
    """

    def __init__(self, driver):
        self.driver = driver
        self._el = Element(driver)

    # ---------- basic checks ----------
    def _any_popover_present(self) -> bool:
        def _see():
            els = self.driver.find_elements(By.CSS_SELECTOR, _POPOVER_WRAPPER_CSS)
            return any((e.is_displayed() for e in els))
        try:
            return _retry_stale(_see)
        except Exception:
            return False

    def is_open(self) -> bool:
        if self._any_popover_present():
            return True
        try:
            return _retry_stale(lambda: any(b.is_displayed() for b in self.driver.find_elements(By.XPATH, _CLOSE_BDI_BTN_XP)))
        except Exception:
            pass
        try:
            return _retry_stale(lambda: any(b.is_displayed() for b in self.driver.find_elements(By.XPATH, _OK_BDI_BTN_XP)))
        except Exception:
            pass
        return False

    # ---------- text scraping ----------
    def text(self, timeout: float = 0.5) -> str:
        end = time.time() + timeout
        while time.time() < end:
            try:
                el = WebDriverWait(self.driver, 0.25, ignored_exceptions=(StaleElementReferenceException,)).until(
                    EC.presence_of_element_located((By.XPATH, _MSG_ITEM_TITLE_XP))
                )
                if el.is_displayed():
                    try:
                        return el.text.strip()
                    except StaleElementReferenceException:
                        pass
                break
            except Exception:
                pass
        try:
            return (self.driver.execute_script("""
                try{
                  var dlg = document.querySelector("div[role='dialog']");
                  if(!dlg) return '';
                  var h = dlg.querySelector(".sapMDialogTitle, .sapMTitle, [role='heading']");
                  return (h && (h.innerText||h.textContent)||'').trim();
                }catch(e){ return ''; }
            """) or "").strip()
        except Exception:
            return ""

    # ---------- close helpers ----------
    def _try_click_close_button_once(self) -> bool:
        try:
            pops = self.driver.find_elements(By.CSS_SELECTOR, _POPOVER_WRAPPER_CSS)
            for pop in pops:
                try:
                    if not pop.is_displayed():
                        continue
                except StaleElementReferenceException:
                    continue
                try:
                    btn = pop.find_element(By.CSS_SELECTOR, _CLOSE_BTN_CSS)
                except NoSuchElementException:
                    try:
                        btns = self.driver.find_elements(By.CSS_SELECTOR, _CLOSE_BTN_CSS)
                        btn  = next((b for b in btns if b.is_displayed()), None)
                    except StaleElementReferenceException:
                        btn = None
                if btn:
                    try:
                        self._el.js_click(btn)
                        return True
                    except StaleElementReferenceException:
                        pass
        except StaleElementReferenceException:
            return False
        except Exception:
            return False
        return False

    def _js_fallback_close_all_popovers(self) -> bool:
        try:
            return bool(self.driver.execute_script("""
                try{
                  var closed = 0;
                  document.querySelectorAll('button.sapMMsgPopoverCloseBtn').forEach(function(b){
                    try{
                      var r = b.getBoundingClientRect();
                      var visible = !!(r.width || r.height) && window.getComputedStyle(b).visibility !== 'hidden';
                      if (visible) { b.click(); closed++; }
                    }catch(e){}
                  });
                  return closed > 0;
                }catch(e){ return false; }
            """))
        except Exception:
            return False

    def _click_bdi_close(self) -> bool:
        try:
            btn = WebDriverWait(self.driver, 1.5, ignored_exceptions=(StaleElementReferenceException,)).until(
                EC.element_to_be_clickable((By.XPATH, _CLOSE_BDI_BTN_XP))
            )
            try:
                self._el.js_click(btn)
            except Exception:
                try:
                    btn.click()
                except Exception:
                    pass
            return True
        except Exception:
            return False

    def _click_ok(self) -> bool:
        try:
            btn = WebDriverWait(self.driver, 1.0, ignored_exceptions=(StaleElementReferenceException,)).until(
                EC.element_to_be_clickable((By.XPATH, _OK_BDI_BTN_XP))
            )
            try:
                self._el.js_click(btn)
            except Exception:
                try:
                    btn.click()
                except Exception:
                    pass
            return True
        except Exception:
            return False

    # ---------- public API ----------
    def close(self, timeout: float = 2.0) -> bool:
        end = time.time() + max(0.2, timeout)

        while time.time() < end:
            # Popover?
            if self._any_popover_present():
                for _ in (1, 2):
                    if self._try_click_close_button_once():
                        try:
                            WebDriverWait(self.driver, 0.5, ignored_exceptions=(StaleElementReferenceException,)).until_not(
                                EC.presence_of_element_located((By.CSS_SELECTOR, _POPOVER_WRAPPER_CSS))
                            )
                        except Exception:
                            pass
                        if not self._any_popover_present():
                            return True
                if self._js_fallback_close_all_popovers():
                    try:
                        WebDriverWait(self.driver, 0.5, ignored_exceptions=(StaleElementReferenceException,)).until_not(
                            EC.presence_of_element_located((By.CSS_SELECTOR, _POPOVER_WRAPPER_CSS))
                        )
                    except Exception:
                        pass
                    if not self._any_popover_present():
                        return True

            # Dialog “Close”
            if self._click_bdi_close():
                time.sleep(0.15)
                if not self.is_open():
                    return True

            # Dialog “OK” fallback
            if self._click_ok():
                time.sleep(0.15)
                if not self.is_open():
                    return True

            time.sleep(0.12)

        return not self.is_open()
