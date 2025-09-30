# pages/CurrencyExchangeRates/elements/ExcelExport/element.py
from __future__ import annotations

import time
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


class ExcelExporter(Element):
    """
    Clicks the ListReport 'Export' action and waits for an .xlsx file to appear
    in the provided download directory.

    Returns (xlsx_path, size_bytes) on success, or (None, 0) on failure.
    """

    def _click_export_button(self, timeout: int = 15) -> bool:
        # 1) Try via the icon <span> id suffix, then click its owning button
        try:
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
                except Exception:
                    self.js_click(btn)
                wait_ui5_idle(self.driver, timeout=timeout)
                return True
        except Exception:
            pass

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
                btn = WebDriverWait(self.driver, 3).until(
                    EC.element_to_be_clickable((By.XPATH, xp))
                )
                try:
                    self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
                except Exception:
                    pass
                try:
                    btn.click()
                except Exception:
                    self.js_click(btn)
                wait_ui5_idle(self.driver, timeout=timeout)
                return True
            except Exception:
                continue

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
                    except Exception:
                        self.js_click(itm)
                    wait_ui5_idle(self.driver, timeout=6)
                    return
                except Exception:
                    continue
        except Exception:
            pass

    def _wait_xlsx(
        self,
        download_dir: Path,
        timeout: int = 120,
        known: Dict[str, float] | None = None,
        min_mtime: float | None = None,
    ) -> Tuple[Optional[Path], int]:
        end = time.time() + max(1, timeout)
        known = known or {}
        last: Optional[Path] = None
        while time.time() < end:
            for cand in sorted(download_dir.glob("*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True):
                try:
                    resolved = str(cand.resolve())
                    mtime = cand.stat().st_mtime
                except Exception:
                    continue
                if resolved in known and mtime <= known[resolved]:
                    continue
                if min_mtime is not None and mtime < min_mtime:
                    continue
                if cand.with_suffix(cand.suffix + ".crdownload").exists():
                    continue
                try:
                    size = cand.stat().st_size
                except Exception:
                    size = 0
                if size <= 0:
                    continue
                return cand, size
            time.sleep(0.5)
        return last, 0

    def export_now(self, download_dir: Path, timeout: int = 90) -> Tuple[Optional[Path], int]:
        dl_dir = Path(download_dir)
        dl_dir.mkdir(parents=True, exist_ok=True)

        known: Dict[str, float] = {}
        for existing in dl_dir.glob("*.xlsx"):
            try:
                known[str(existing.resolve())] = existing.stat().st_mtime
            except Exception:
                continue

        for partial in dl_dir.glob("*.crdownload"):
            try:
                partial.unlink()
            except Exception:
                pass

        start_mtime = time.time()
        if not self._click_export_button(timeout=min(timeout, 20)):
            return None, 0
        self._maybe_click_menu_item()
        return self._wait_xlsx(dl_dir, timeout=timeout, known=known, min_mtime=start_mtime)
