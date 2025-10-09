# pages/CurrencyExchangeRates/elements/DraftFinder/element.py
from __future__ import annotations

import time
import logging
from logging.handlers import RotatingFileHandler
from typing import List, Tuple

from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    StaleElementReferenceException,
    TimeoutException,
    ElementClickInterceptedException,
    ElementNotInteractableException,
)

from core.base import Element
from services.ui import wait_ui5_idle

def _ensure_logger() -> logging.Logger:
    log = logging.getLogger("sapbot.ui.drafts")
    if not log.handlers:
        log.setLevel(logging.DEBUG)
        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)
        ch.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] drafts %(message)s"))
        log.addHandler(ch)
        log_dir = Path("WebService") / "logs"
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        fh = RotatingFileHandler(log_dir / "sapbot.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s %(message)s"))
        log.addHandler(fh)
    return log

from pathlib import Path
log = _ensure_logger()

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


# ---------- Selectors (robust by suffix/text) ----------
DATE_INPUT_INNER_XP = (
    "//input[substring(@id,string-length(@id)-string-length("
    "'ExchangeRateEffectiveDateFoEd-input-inner')+1)='ExchangeRateEffectiveDateFoEd-input-inner']"
)

ROW_XP = "//main//table//tbody/tr[contains(@id,'ListReportTable:::ColumnListItem')]"
ROW_IS_DRAFT_REL_XP = (
    "./td[8]//a[contains(@id,'DraftObjectMarker')]"
    "[.//span[contains(normalize-space(),'Draft')]]"
)
ROW_CHECKBOX_REL_XP = (
    ".//*[@role='checkbox' and (contains(@id,'selectMulti') or contains(@class,'sapMCb'))]"
    " | .//div[contains(@class,'sapMCb') and contains(@id,'selectMulti')]"
)
LIST_DELETE_BTN_XP = (
    "//button[substring(@id,string-length(@id)-string-length('--deleteEntry')+1)='--deleteEntry']"
    " | //bdi[normalize-space()='Delete']/ancestor::button[1]"
)

DIALOG_ROOT_XP = "//div[@role='alertdialog' or contains(@class,'sapMDialog')]"
DIALOG_DELETE_BTN_XP = (
    "("
    "//div[@role='alertdialog' or contains(@class,'sapMDialog')]"
    "//button[.//bdi[normalize-space()='Delete']]"
    ")[last()]"
)


class DraftFinder(Element):
    """
    UI helper to:
      - Set the List Report 'Exchange Rate Effective Date' and APPLY (Enter)
      - Wait until table rows are (re)loaded
      - Pre-scroll a couple times to trigger initial row rendering
      - Detect draft rows
      - Delete draft rows (check → Delete → confirm)
    """

    # ---------- Date filter ----------
    def set_effective_date_and_apply(self, dd_mm_yyyy: str, timeout: int = 20) -> bool:
        log.info("drafts: set filter date → %s", dd_mm_yyyy)
        wait = WebDriverWait(self.driver, timeout)
        try:
            inp = wait.until(EC.element_to_be_clickable((By.XPATH, DATE_INPUT_INNER_XP)))
        except TimeoutException:
            log.error("drafts: date input not clickable (timeout=%s)", timeout)
            return False

        def _focus():
            try:
                self.js_click(inp)
            except Exception:
                inp.click()

        _retry_stale(_focus)
        # Hard clear
        for fn in (
            lambda: inp.clear(),
            lambda: inp.send_keys(Keys.CONTROL, "a"),
            lambda: inp.send_keys(Keys.DELETE),
        ):
            try:
                _retry_stale(fn)
            except Exception:
                pass

        _retry_stale(lambda: inp.send_keys(dd_mm_yyyy))
        _retry_stale(lambda: inp.send_keys(Keys.ENTER))  # APPLY
        # tiny blur to ensure binding fires
        try:
            self.driver.execute_script(
                "arguments[0].dispatchEvent(new Event('change',{bubbles:true}));"
                "arguments[0].blur && arguments[0].blur();",
                inp,
            )
        except Exception:
            pass

        wait_ui5_idle(self.driver, timeout=max(8, timeout))
        time.sleep(0.2)
        log.debug("drafts: date applied, waiting rows to (re)load")
        return True

    # ---------- Table readiness ----------
    def wait_rows_loaded(self, timeout: int = 12) -> bool:
        end = time.time() + max(1, timeout)
        while time.time() < end:
            try:
                rows = self.driver.find_elements(By.XPATH, ROW_XP)
                if rows:
                    log.info("drafts: table shows %d row element(s) (initial read)", len(rows))
                    return True
            except Exception:
                pass
            wait_ui5_idle(self.driver, timeout=2)
            time.sleep(0.15)
        log.info("drafts: no visible rows; proceeding anyway")
        return True

    # ---------- Scrolling ----------
    def pre_scroll(self, times: int = 2, settle: float = 0.4):
        log.debug("drafts: pre_scroll times=%s", times)
        try:
            body = self.driver.find_element(By.TAG_NAME, "body")
        except Exception:
            return
        for _ in range(max(0, int(times))):
            try:
                body.send_keys(Keys.PAGE_DOWN)
            except Exception:
                pass
            wait_ui5_idle(self.driver, timeout=6)
            time.sleep(settle)

    # ---------- Rows & Draft detection ----------
    def _rows_now(self):
        return self.driver.find_elements(By.XPATH, ROW_XP)

    def visible_draft_rows(self) -> List:
        rows = self._rows_now()
        out = []
        for r in rows:
            try:
                if r.find_elements(By.XPATH, ROW_IS_DRAFT_REL_XP):
                    out.append(r)
            except StaleElementReferenceException:
                continue
        log.info("drafts: visible draft rows=%d", len(out))
        return out

    # ---------- Delete helpers ----------
    def _tick_row_checkbox(self, row) -> bool:
        try:
            cb = row.find_element(By.XPATH, ROW_CHECKBOX_REL_XP)
        except Exception:
            log.debug("drafts: row checkbox not found")
            return False

        def _scroll_into_view(el):
            try:
                self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
            except Exception:
                pass

        def _checked() -> bool:
            try:
                state = (cb.get_attribute("aria-checked") or "").strip().lower()
                if state == "true":
                    return True
                inner = None
                try:
                    inner = cb.find_element(By.XPATH, ".//*[@aria-checked]")
                except Exception:
                    inner = None
                if inner:
                    st2 = (inner.get_attribute("aria-checked") or "").strip().lower()
                    return st2 == "true"
                return False
            except Exception:
                return False

        if _checked():
            log.debug("drafts: checkbox already checked")
            return True

        _scroll_into_view(row)
        _scroll_into_view(cb)
        try:
            self.js_click(cb)
            how = "js"
        except Exception:
            how = "native?"
        time.sleep(0.05)
        if _checked():
            log.debug("drafts: checkbox checked (%s)", how)
            return True

        try:
            cb.click()
        except (ElementClickInterceptedException, ElementNotInteractableException):
            pass
        except Exception:
            pass
        time.sleep(0.05)
        if _checked():
            log.debug("drafts: checkbox checked (native)")
            return True

        try:
            row.click()
        except Exception:
            pass
        try:
            row.send_keys(Keys.SPACE)
        except Exception:
            pass
        time.sleep(0.08)
        if _checked():
            log.debug("drafts: checkbox checked (SPACE)")
            return True

        try:
            first_cell = row.find_element(By.XPATH, "./td[1]")
            _scroll_into_view(first_cell)
            try:
                self.js_click(first_cell)
            except Exception:
                try:
                    first_cell.click()
                except Exception:
                    pass
        except Exception:
            pass
        time.sleep(0.08)
        ok = _checked()
        log.debug("drafts: checkbox final state=%s", ok)
        return ok

    def _click_list_delete(self, timeout: int = 8) -> bool:
        try:
            btn = WebDriverWait(self.driver, timeout).until(
                EC.element_to_be_clickable((By.XPATH, LIST_DELETE_BTN_XP))
            )
        except TimeoutException:
            log.error("drafts: list Delete button not clickable")
            return False
        try:
            self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
        except Exception:
            pass
        try:
            btn.click()
            how = "native"
        except Exception:
            try:
                self.js_click(btn)
                how = "js"
            except Exception:
                log.error("drafts: could not click list Delete")
                return False
        log.info("drafts: clicked list Delete (%s)", how)
        wait_ui5_idle(self.driver, timeout=timeout)
        return True

    def _confirm_dialog_delete(self, timeout: int = 12) -> bool:
        try:
            WebDriverWait(self.driver, min(6, timeout)).until(
                EC.presence_of_element_located((By.XPATH, DIALOG_ROOT_XP))
            )
        except TimeoutException:
            log.debug("drafts: no explicit confirm dialog (maybe auto-confirm)")
            # continue

        try:
            btn = WebDriverWait(self.driver, timeout).until(
                EC.element_to_be_clickable((By.XPATH, DIALOG_DELETE_BTN_XP))
            )
        except TimeoutException:
            log.error("drafts: confirm Delete button not found")
            return False

        try:
            self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
        except Exception:
            pass
        try:
            btn.click()
            how = "native"
        except Exception:
            try:
                self.js_click(btn)
                how = "js"
            except Exception:
                log.error("drafts: failed to click confirm Delete")
                return False

        log.info("drafts: confirmed Delete (%s)", how)
        wait_ui5_idle(self.driver, timeout=timeout)
        try:
            WebDriverWait(self.driver, min(6, timeout)).until_not(
                EC.presence_of_element_located((By.XPATH, DIALOG_ROOT_XP))
            )
        except Exception:
            pass
        return True

    # ---------- Public: delete all visible drafts ----------
    def delete_visible_drafts(self, per_click_timeout: int = 12):
        """
        Returns (deleted_count, attempts, deleted_sample:list[str])
        """
        deleted = 0
        attempts = 0
        sample: list[str] = []

        log.info("drafts: starting deletion loop (timeout per step=%s)", per_click_timeout)

        while True:
            drafts = self.visible_draft_rows()
            if not drafts:
                log.info("drafts: no more draft rows visible → stop")
                break

            row = drafts[0]
            attempts += 1

            try:
                from_ccy = (row.find_element(By.XPATH, "./td[2]").text or "").strip()
                to_ccy   = (row.find_element(By.XPATH, "./td[3]").text or "").strip()
                date_txt = (row.find_element(By.XPATH, "./td[4]").text or "").strip()
                label = f"{from_ccy}->{to_ccy} @ {date_txt}"
            except Exception:
                label = "draft-row"
            log.info("drafts: attempt=%d deleting %s", attempts, label)

            if not self._tick_row_checkbox(row):
                log.warning("drafts: could not tick checkbox; refreshing rows")
                wait_ui5_idle(self.driver, timeout=4)
                time.sleep(0.2)
                continue

            if not self._click_list_delete(timeout=per_click_timeout):
                log.warning("drafts: list Delete click failed; retrying loop")
                continue

            if self._confirm_dialog_delete(timeout=per_click_timeout):
                deleted += 1
                if len(sample) < 10:
                    sample.append(label)
                log.info("drafts: deleted OK (%s) | total deleted=%d", label, deleted)
            else:
                log.error("drafts: confirm delete failed for %s", label)

            wait_ui5_idle(self.driver, timeout=per_click_timeout)
            time.sleep(0.25)

        log.info("drafts: loop complete → deleted=%d attempts=%d", deleted, attempts)
        return deleted, attempts, sample
