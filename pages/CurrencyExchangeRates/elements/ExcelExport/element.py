# pages/CurrencyExchangeRates/elements/ExcelExport/element.py
from __future__ import annotations

import time
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Dict, Optional, Tuple

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from core.base import Element
from services.ui import wait_ui5_idle
from .selectors import (
    EXPORT_SPLIT_BTN_IMG_ID_SUFFIX,
    EXPORT_BTN_GENERIC_XP,
)

# -------------------- logging --------------------
def _ensure_logger() -> logging.Logger:
    log = logging.getLogger("sapbot.ui.excel")
    if not log.handlers:
        log.setLevel(logging.DEBUG)
        # console
        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)
        ch.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] excel %(message)s"))
        log.addHandler(ch)
        # rotating file
        log_dir = Path("WebService") / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        fh = RotatingFileHandler(log_dir / "sapbot.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s %(message)s"))
        log.addHandler(fh)
    return log

log = _ensure_logger()
# -------------------------------------------------


class ExcelExporter(Element):
    """
    Clicks the ListReport 'Export' action and waits for an .xlsx file to appear
    in the provided download directory.

    Returns (xlsx_path, size_bytes) on success, or (None, 0) on failure.
    """

    # -------------------- UI helpers --------------------

    def _click_export_button(self, timeout: int = 15) -> bool:
        log.info("export: trying to click Export (timeout=%s)", timeout)

        # 1) Try via the icon <span> id suffix, then click its owning button
        try:
            log.debug("export: probing icon suffix %r", EXPORT_SPLIT_BTN_IMG_ID_SUFFIX)
            btn_id = self.driver.execute_script(
                """
                var suf = arguments[0];
                var nodes = document.querySelectorAll('[id$="'+suf+'"]');
                function visible(el){
                  if(!el) return false;
                  var cs=getComputedStyle(el);
                  if(cs.display==='none'||cs.visibility==='hidden') return false;
                  var r=el.getBoundingClientRect();
                  return (r.width>0 && r.height>0);
                }
                for (var i=nodes.length-1;i>=0;i--){
                  var el=nodes[i]; if(!visible(el)) continue;
                  var btn = el.closest('button');
                  if(btn) return btn.id;
                }
                return null;
                """,
                EXPORT_SPLIT_BTN_IMG_ID_SUFFIX
            )
            log.debug("export: icon-suffix → btn_id=%r", btn_id)
            if btn_id:
                btn = WebDriverWait(self.driver, timeout).until(
                    EC.element_to_be_clickable((By.ID, btn_id))
                )
                try:
                    self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
                except Exception:
                    pass
                try:
                    btn.click()
                    how = "native-click"
                except Exception:
                    self.js_click(btn)
                    how = "js-click"
                log.info("export: clicked split-button via id=%s (%s)", btn_id, how)
                wait_ui5_idle(self.driver, timeout=timeout)
                return True
        except Exception as e:
            log.debug("export: split-button path failed: %s: %s", type(e).__name__, e)

        # 2) Fallbacks by label/aria/title/xpath
        variants = [
            EXPORT_BTN_GENERIC_XP,
            "//button[.//bdi[contains(normalize-space(),'Export to Spreadsheet')]]",
            "//button[.//bdi[normalize-space()='Export']]",
            "//button[@aria-label='Export' or @title='Export']",
            "//button[contains(@id,'btnExcelExport')]",
        ]
        for xp in variants:
            try:
                log.debug("export: trying xpath: %s", xp)
                btn = WebDriverWait(self.driver, 3).until(
                    EC.element_to_be_clickable((By.XPATH, xp))
                )
                try:
                    self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
                except Exception:
                    pass
                try:
                    btn.click()
                    how = "native"
                except Exception:
                    self.js_click(btn)
                    how = "js"
                log.info("export: clicked Export via xpath (%s)", how)
                wait_ui5_idle(self.driver, timeout=timeout)
                return True
            except Exception as e:
                log.debug("export: xpath failed: %s", e)

        log.warning("export: could not find any clickable Export button")
        return False

    def _maybe_click_menu_item(self) -> None:
        """
        Some UIs open a mini menu after the split button.
        Try a couple of common menu item locators.
        """
        try:
            for xp in (
                "//div[contains(@class,'sapMSelectList') or contains(@class,'sapMList')]//span[normalize-space()='Export']",
                "//bdi[normalize-space()='Export to Spreadsheet']/ancestor::button[1]",
                "//bdi[normalize-space()='Export']/ancestor::button[1]",
            ):
                try:
                    itm = WebDriverWait(self.driver, 2).until(
                        EC.element_to_be_clickable((By.XPATH, xp))
                    )
                    try:
                        itm.click()
                        how = "native"
                    except Exception:
                        self.js_click(itm)
                        how = "js"
                    log.info("export: clicked menu item via xpath=%s (%s)", xp, how)
                    wait_ui5_idle(self.driver, timeout=6)
                    return
                except Exception:
                    continue
        except Exception as e:
            log.debug("export: _maybe_click_menu_item failed: %s: %s", type(e).__name__, e)

    # -------------------- FS helpers --------------------

    def _purge_partial_downloads(self, folder: Path) -> None:
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        n = 0
        for p in list(folder.glob("*.crdownload")):
            try:
                p.unlink()
                n += 1
            except Exception:
                pass
        if n:
            log.debug("export: purged %d stale .crdownload file(s) from %s", n, folder)

    def _purge_old_xlsx(self, folder: Path) -> None:
        n = 0
        for p in list(folder.glob("*.xlsx")):
            try:
                p.unlink()
                n += 1
            except Exception:
                pass
        if n:
            log.debug("export: purged %d pre-existing .xlsx in %s", n, folder)

    def _collect_known(self, folder: Path) -> Dict[str, float]:
        known: Dict[str, float] = {}
        for existing in folder.glob("*.xlsx"):
            try:
                known[str(existing.resolve())] = existing.stat().st_mtime
            except Exception:
                continue
        log.debug("export: known .xlsx before click: %d", len(known))
        return known

    # -------------------- Wait logic --------------------

    def _wait_xlsx(
        self,
        download_dir: Path,
        timeout: int = 120,
        known: Dict[str, float] | None = None,
        min_mtime: float | None = None,
        stable_checks: int = 3,
        poll: float = 0.30,
    ) -> Tuple[Optional[Path], int]:
        """
        Waits for a *new* .xlsx file. We accept a candidate if:
          - it's not in `known`, OR
          - its mtime >= min_mtime, OR
          - its ctime >= min_mtime   <-- important for servers setting old Last-Modified
        And we still require: no .crdownload sibling, size > 0, and size stable for a few polls.
        """
        end = time.time() + max(1, timeout)
        known = known or {}

        last_size = -1
        stable = 0
        last_path: Optional[Path] = None

        log.info("export: waiting for .xlsx in %s (timeout=%ss, min_mtime=%s)", download_dir, timeout, min_mtime)

        while time.time() < end:
            newest: tuple[float, Path] | None = None

            for cand in download_dir.glob("*.xlsx"):
                try:
                    st = cand.stat()
                    resolved = str(cand.resolve())
                    mtime = st.st_mtime
                    ctime = getattr(st, "st_ctime", mtime)  # Windows has true ctime; POSIX shows inode change time
                except Exception:
                    continue

                if cand.with_suffix(cand.suffix + ".crdownload").exists():
                    log.debug("export: skip %s (still .crdownload present)", cand.name)
                    continue

                # decide if this is "new enough"
                in_known = resolved in known and mtime <= known[resolved]
                m_ok = (min_mtime is None) or (mtime >= min_mtime)
                c_ok = (min_mtime is None) or (ctime >= min_mtime)

                if in_known and not (m_ok or c_ok):
                    # Old file we already had and neither mtime nor ctime moved past start — skip
                    log.debug("export: skip older file %s (mtime<min_mtime AND ctime<min_mtime)", cand.name)
                    continue

                # candidate is acceptable; pick the most recent by max(mtime, ctime)
                freshness = max(mtime, ctime)
                if (newest is None) or (freshness > newest[0]):
                    newest = (freshness, cand)

            if newest:
                cand = newest[1]
                try:
                    size = cand.stat().st_size
                except Exception:
                    size = 0

                log.debug("export: candidate %s size=%s stable=%s/%s", cand.name, size, stable, stable_checks)

                if size > 0:
                    if last_path is not None and cand == last_path and size == last_size:
                        stable += 1
                    else:
                        stable = 0
                        last_path = cand
                        last_size = size

                    if stable >= stable_checks:
                        log.info("export: using %s (size=%d)", cand, size)
                        return cand, size

            time.sleep(poll)

        log.warning("export: no fresh .xlsx detected within timeout")
        return None, 0

    def export_now(
        self,
        download_dir: Path,
        timeout: int = 90,
        purge_old_xlsx: bool = False,  # set True if the filename is always the same like "Exchange Rates.xlsx"
    ) -> Tuple[Optional[Path], int]:
        dl_dir = Path(download_dir).expanduser().resolve()
        dl_dir.mkdir(parents=True, exist_ok=True)
        log.info("export: begin (download_dir=%s, purge_old=%s)", dl_dir, purge_old_xlsx)

        known = self._collect_known(dl_dir)
        self._purge_partial_downloads(dl_dir)

        # Optional: remove pre-existing .xlsx so the next file cannot be “old” by definition
        if purge_old_xlsx:
            self._purge_old_xlsx(dl_dir)
            known = {}  # nothing is known anymore

        start_mtime = time.time()

        if not self._click_export_button(timeout=min(timeout, 20)):
            log.error("export: failed to click Export button")
            return None, 0

        self._maybe_click_menu_item()

        path, size = self._wait_xlsx(
            dl_dir,
            timeout=timeout,
            known=known,
            min_mtime=start_mtime,
            stable_checks=3,
            poll=0.30,
        )
        log.info("export: done (path=%s, size=%s)", path, size)
        return path, size
