# elements/Footer/element.py
import time
from typing import Callable, Dict

from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException, StaleElementReferenceException

from core.base import Element, fluent_wait
from services.ui import wait_ui5_idle
from ..Dialog.element import DialogWatcher
from ..Toast.element import ToastReader
from ..Messages.element import Ui5Messages
from ..Status.element import StatusProbe
from .selectors import (
    ACTIVATE_CREATE_BTN_XPATH,
    FORM_CREATE_OR_SAVE_BTN_XPATH,
    ACTIVATE_CREATE_BTN_CSS,
    HEADER_TITLE_ID_SUFFIX,
    EDIT_BTN_ID_SUFFIX,
    DISCARD_BTN_ID_SUFFIX,
    COPY_BTN_ID_CONTAINS,
    MESSAGE_BTN_SUFFIX,
    MSG_POPOVER_CLOSE_BTN_XP,
    MSG_ITEMS_XP, 
)

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


class FooterActions(Element):
    """
    Submit logic with:
      - first attempt click
      - loop clicking with DOM/MessageManager checks
      - uses StatusProbe for robust success detection
    """

    EXTRA_SETTLE_SEC = 0.2  # trimmed
    def open_and_read_messages(self, timeout: int = 8) -> list[str]:
        """
        Clicks the footer 'Messages' button to open the Message Popover (if badge > 0),
        returns a list of visible message titles (strings). Leaves the popover open.
        """
        # Find the footer messages button
        try:
            msg_btn_id = self._query_visible_by_suffix(MESSAGE_BTN_SUFFIX)
        except Exception:
            msg_btn_id = None

        if not msg_btn_id:
            return []

        # Read the badge text quickly (optional; if not found, still click)
        badge_text = ""
        try:
            badge_bdi = self.driver.find_element(By.ID, f"{msg_btn_id}-BDI-content")
            badge_text = (badge_bdi.text or "").strip()
        except Exception:
            pass

        # If nothing to show (badge empty/0), bail early
        if badge_text and badge_text.isdigit() and int(badge_text) == 0:
            return []

        # Open the popover (toggle)
        try:
            btn = WebDriverWait(self.driver, 3, ignored_exceptions=(StaleElementReferenceException,)).until(
                EC.element_to_be_clickable((By.ID, msg_btn_id))
            )
            try:
                self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
            except Exception:
                pass
            try:
                btn.click()
            except Exception:
                try:
                    self.driver.execute_script("arguments[0].click();", btn)
                except Exception:
                    pass
        except Exception:
            return []

        # Wait for message items to render
        try:
            WebDriverWait(self.driver, timeout, ignored_exceptions=(StaleElementReferenceException,)).until(
                EC.presence_of_element_located((By.XPATH, MSG_ITEMS_XP))
            )
        except TimeoutException:
            return []

        # Collect item titles
        texts = []
        try:
            items = self.driver.find_elements(By.XPATH, MSG_ITEMS_XP)
            for it in items:
                try:
                    txt = (it.text or "").strip()
                    if txt:
                        texts.append(txt)
                except Exception:
                    continue
        except Exception:
            pass
        return texts


    # ---------- finding & UI5 press helpers ----------
    def _query_visible_by_suffix(self, suffix: str) -> str | None:
        try:
            return self.driver.execute_script(
                """
                var suffix = arguments[0];
                var nodes = document.querySelectorAll("[id$='"+suffix.replace(/([.*+?^${}()|[\\]\\\\])/g,'\\\\$1')+"']");
                function vis(el){ if(!el) return false; var cs=getComputedStyle(el);
                  if(cs.display==='none'||cs.visibility==='hidden') return false;
                  var r=el.getBoundingClientRect(); return (r.width>0 && r.height>0); }
                for (var i=nodes.length-1;i>=0;i--){ if (vis(nodes[i])) return nodes[i].id||null; }
                return null;
                """,
                suffix,
            )
        except Exception:
            return None

    def _header_aria_label(self) -> str:
        try:
            return self.driver.execute_script(
                """
                var suf = arguments[0];
                var nodes = document.querySelectorAll("[id$='"+suf.replace(/([.*+?^${}()|[\\]\\\\])/g,'\\\\$1')+"']");
                function vis(el){ if(!el) return false; var cs=getComputedStyle(el);
                  if(cs.display==='none'||cs.visibility==='hidden') return false;
                  var r=el.getBoundingClientRect(); return (r.width>0 && r.height>0); }
                for (var i=nodes.length-1;i>=0;i--){ var el=nodes[i]; if(!vis(el)) continue;
                  var a=(el.getAttribute('aria-label')||'').trim(); if(a) return a; }
                return '';
                """,
                HEADER_TITLE_ID_SUFFIX,
            ) or ""
        except Exception:
            return ""

    def _query_activate_id(self) -> str | None:
        try:
            return self.driver.execute_script(
                """
                var sel = arguments[0], nodes = document.querySelectorAll(sel);
                function vis(el){ if(!el) return false; var cs=getComputedStyle(el);
                  if(cs.display==='none'||cs.visibility==='hidden') return false;
                  var r=el.getBoundingClientRect(); return (r.width>0 && r.height>0); }
                for (var i=nodes.length-1;i>=0;i--){ if (vis(nodes[i])) return nodes[i].id||null; }
                return null;
                """,
                ACTIVATE_CREATE_BTN_CSS,
            )
        except Exception:
            return None

    def _really_clickable(self, dom_id: str) -> bool:
        try:
            return bool(self.driver.execute_script(
                """
                try {
                  var el=document.getElementById(arguments[0]); if(!el) return false;
                  var cs=getComputedStyle(el);
                  if(cs.display==='none'||cs.visibility==='hidden') return false;
                  if(el.disabled) return false;
                  if((' '+el.className+' ').indexOf(' sapMBtnDisabled ')>=0) return false;
                  var r=el.getBoundingClientRect();
                  if (r.width<=0 || r.height<=0) return false;
                  var cx=r.left+r.width/2, cy=r.top+r.height/2;
                  var at=document.elementFromPoint(Math.max(0,cx),Math.max(0,cy));
                  return !!(at && (at===el || el.contains(at)));
                }catch(e){ return false; }
                """,
                dom_id
            ))
        except Exception:
            return False

    def _ui5_press_by_id(self, dom_id: str) -> str:
        try:
            res = self.driver.execute_script(
                """
                try {
                  var id = arguments[0];
                  var ctrl = sap && sap.ui && sap.ui.getCore ? sap.ui.getCore().byId(id) : null;
                  if (ctrl && ctrl.firePress) { ctrl.firePress(); return 'ui5-firePress'; }
                  if (ctrl && ctrl.press)     { ctrl.press();     return 'ui5-press'; }
                  var el = document.getElementById(id);
                  if (el) { el.click(); return 'dom-click-fallback'; }
                  return 'ui5-miss';
                } catch(e){ return 'ui5-exc:'+String(e); }
                """,
                dom_id,
            )
            return str(res)
        except Exception as e:
            return f"ui5-exc:{type(e).__name__}"

    def _press_activate_best_effort(self) -> bool:
        act_id = self._query_activate_id()
        if act_id:
            try:
                def _get_el():
                    return self.driver.find_element(By.ID, act_id)
                el = _retry_stale(_get_el)

                try:
                    self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
                except Exception:
                    pass

                if self._really_clickable(act_id):
                    try:
                        _retry_stale(lambda: el.click())
                        wait_ui5_idle(self.driver, timeout=min(4, self._timeout))
                        time.sleep(self.EXTRA_SETTLE_SEC)
                        return True
                    except Exception:
                        pass

                try:
                    self.driver.execute_script("arguments[0].click();", el)
                    wait_ui5_idle(self.driver, timeout=min(4, self._timeout))
                    time.sleep(self.EXTRA_SETTLE_SEC)
                    return True
                except Exception:
                    pass

                _ = self._ui5_press_by_id(act_id)
                wait_ui5_idle(self.driver, timeout=min(4, self._timeout))
                time.sleep(self.EXTRA_SETTLE_SEC)
                return True
            except Exception:
                pass

        # Fallback: generic Create/Save by text
        try:
            btn = fluent_wait(self.driver, 1.5, poll=0.15).until(
                EC.element_to_be_clickable((By.XPATH, FORM_CREATE_OR_SAVE_BTN_XPATH))
            )
            try:
                self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
            except Exception:
                pass
            try:
                _retry_stale(lambda: btn.click())
            except Exception:
                try:
                    self.driver.execute_script("arguments[0].click();", btn)
                except Exception:
                    pass
            wait_ui5_idle(self.driver, timeout=min(4, self._timeout))
            time.sleep(self.EXTRA_SETTLE_SEC)
            return True
        except Exception:
            pass

        # Final fallback: Ctrl+S
        try:
            ActionChains(self.driver).key_down(Keys.CONTROL).send_keys("s").key_up(Keys.CONTROL).perform()
            wait_ui5_idle(self.driver, timeout=min(4, self._timeout))
            time.sleep(self.EXTRA_SETTLE_SEC)
            return True
        except Exception:
            return False

    # Kept for backward compatibility as a last-resort fallback
    def _activated_dom(self) -> bool:
        try:
            has_edit    = bool(self._query_visible_by_suffix(EDIT_BTN_ID_SUFFIX))
            has_discard = bool(self._query_visible_by_suffix(DISCARD_BTN_ID_SUFFIX))
            aria        = (self._header_aria_label() or "")
            if has_edit and not has_discard:
                return True
            if aria and ("Header area" in aria) and ("New" not in aria):
                return True
            return False
        except Exception:
            return False

    def click_create(self, clicks: int = 1) -> dict:
        info = {"clicks": 0, "dialogs": [], "toasts": []}
        dlg = DialogWatcher(self.driver)
        reader = ToastReader(self.driver)

        for _ in range(max(1, clicks)):
            if dlg.is_open():
                info["dialogs"].append(dlg.text() or "")
                break

            pressed = self._press_activate_best_effort()
            if not pressed:
                continue

            info["clicks"] += 1
            wait_ui5_idle(self.driver, timeout=min(6, self._timeout))
            time.sleep(self.EXTRA_SETTLE_SEC)

            try:
                t = reader.read_last()
                if t:
                    info["toasts"].append(t)
            except Exception:
                pass

            if dlg.is_open():
                info["dialogs"].append(dlg.text() or "")
                break

        return info

    def close_message_popover_if_open(self, timeout: int = 3) -> bool:
        """
        Closes the Message Popover if it is open. Returns True if we believe it closed.
        """
        # Prefer the close button in the popover header
        try:
            close_btn = WebDriverWait(self.driver, 1.5, ignored_exceptions=(StaleElementReferenceException,)).until(
                EC.element_to_be_clickable((By.XPATH, MSG_POPOVER_CLOSE_BTN_XP))
            )
            try:
                close_btn.click()
            except Exception:
                try:
                    self.driver.execute_script("arguments[0].click();", close_btn)
                except Exception:
                    pass
            # Wait until close button disappears
            WebDriverWait(self.driver, timeout, ignored_exceptions=(StaleElementReferenceException,)).until_not(
                EC.presence_of_element_located((By.XPATH, MSG_POPOVER_CLOSE_BTN_XP))
            )
            return True
        except Exception:
            # Fallback: toggle the Messages button to close
            try:
                msg_btn_id = self._query_visible_by_suffix(MESSAGE_BTN_SUFFIX)
                if msg_btn_id:
                    btn = self.driver.find_element(By.ID, msg_btn_id)
                    try:
                        btn.click()
                    except Exception:
                        self.driver.execute_script("arguments[0].click();", btn)
                    return True
            except Exception:
                pass
            return False

    def discard_draft(self, timeout: int = 10) -> bool:
        """
        Clicks footer 'Discard Draft', then confirms 'Discard' in the confirmation popover.
        Returns True if confirmation popover disappears.
        """
        import time

        # 1) Click footer 'Discard Draft'
        disc_id = None
        try:
            disc_id = self._query_visible_by_suffix("--discard")
        except Exception:
            pass

        if disc_id:
            try:
                el = WebDriverWait(self.driver, 2, ignored_exceptions=(StaleElementReferenceException,)).until(
                    EC.element_to_be_clickable((By.ID, disc_id))
                )
                try:
                    self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
                except Exception:
                    pass
                try:
                    el.click()
                except Exception:
                    try:
                        self.driver.execute_script("arguments[0].click();", el)
                    except Exception:
                        pass
            except Exception:
                pass
            # UI5 press fallback
            _ = self._ui5_press_by_id(disc_id)

        wait_ui5_idle(self.driver, timeout=min(self._timeout, 4))
        time.sleep(self.EXTRA_SETTLE_SEC)

        # 2) Confirm 'Discard' in popover
        CONFIRM_SUFFIX = "--DiscardDraftConfirmButton"

        def _click_confirm() -> bool:
            # by ID suffix
            try:
                cid = self._query_visible_by_suffix(CONFIRM_SUFFIX)
            except Exception:
                cid = None

            if cid:
                try:
                    btn = WebDriverWait(self.driver, 1.5, ignored_exceptions=(StaleElementReferenceException,)).until(
                        EC.element_to_be_clickable((By.ID, cid))
                    )
                    try:
                        self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
                    except Exception:
                        pass
                    try:
                        btn.click()
                    except Exception:
                        try:
                            self.driver.execute_script("arguments[0].click();", btn)
                        except Exception:
                            pass
                    return True
                except Exception:
                    pass

            # by visible text
            try:
                xp = ("//bdi[normalize-space()='Discard']/ancestor::button[1]"
                    " | //button[.//bdi[normalize-space()='Discard']]")
                btn = WebDriverWait(self.driver, 1.5, ignored_exceptions=(StaleElementReferenceException,)).until(
                    EC.element_to_be_clickable((By.XPATH, xp))
                )
                try:
                    self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
                except Exception:
                    pass
                try:
                    btn.click()
                except Exception:
                    try:
                        self.driver.execute_script("arguments[0].click();", btn)
                    except Exception:
                        pass
                return True
            except Exception:
                return False

        clicked = _click_confirm()
        wait_ui5_idle(self.driver, timeout=min(self._timeout, 4))
        time.sleep(self.EXTRA_SETTLE_SEC)

        # If confirm button no longer visible, assume success
        try:
            still = self._query_visible_by_suffix(CONFIRM_SUFFIX)
        except Exception:
            still = None
        return bool(clicked and not still)

    def ensure_created_by_loop_clicking(
        self,
        object_header_ready: Callable[[], bool],
        at_list: Callable[[], bool],
        close_side: Callable[[], bool],
        max_clicks: int = 5,       # was 10
        total_timeout: int = 35,   # default; caller may override
    ) -> Dict:
        dlg   = DialogWatcher(self.driver)
        reader= ToastReader(self.driver)
        msgs  = Ui5Messages(self.driver)
        probe = StatusProbe(self.driver)

        end = time.time() + max(total_timeout, self._timeout)
        clicks = 0
        toasts = []
        msgs.clear()

        while clicks < max(max_clicks,1) and time.time() < end:
            if dlg.is_open():
                return {
                    "status": "dialog_open",
                    "dialog_open": True,
                    "dialog_text": dlg.text(),
                    "footer_clicks": clicks,
                    "intermediate_toasts": toasts,
                    "messages": msgs.read_all(),
                    "popover_text": msgs.popover_text(),
                }

            if msgs.has_errors():
                return {
                    "status": "activation_error",
                    "dialog_open": False,
                    "dialog_text": "",
                    "footer_clicks": clicks,
                    "intermediate_toasts": toasts,
                    "messages": msgs.errors(),
                    "popover_text": msgs.popover_text(),
                }

            if (
                probe.success()
                or probe.is_persisted_object_page()
                or object_header_ready()
                or at_list()
                or self._activated_dom()
            ):
                close_side()
                return {
                    "status": "created",
                    "dialog_open": False,
                    "dialog_text": "",
                    "footer_clicks": clicks,
                    "intermediate_toasts": toasts,
                    "messages": msgs.read_all(),
                    "popover_text": msgs.popover_text(),
                }

            if self._press_activate_best_effort():
                clicks += 1
                wait_ui5_idle(self.driver, timeout=min(6, self._timeout))
                time.sleep(self.EXTRA_SETTLE_SEC)

            try:
                t = reader.read_last()
                if t:
                    toasts.append(t)
                    lt = (t or "").lower()
                    if any(k in lt for k in ("created", "saved", "activated", "has been created", "successfully")):
                        if not (probe.success() or probe.is_persisted_object_page()):
                            wait_ui5_idle(self.driver, timeout=min(2, self._timeout))
                        close_side()
                        return {
                            "status": "created",
                            "dialog_open": False,
                            "dialog_text": "",
                            "footer_clicks": clicks,
                            "intermediate_toasts": toasts,
                            "messages": msgs.read_all(),
                            "popover_text": msgs.popover_text(),
                        }
            except Exception:
                pass

            time.sleep(0.2)

        if not at_list():
            close_side()

        created = (
            probe.success()
            or probe.is_persisted_object_page()
            or at_list()
            or object_header_ready()
            or self._activated_dom()
        )
        return {
            "status": "created" if created else "unknown",
            "footer_clicks": clicks,
            "intermediate_toasts": toasts,
            "dialog_open": False if not dlg.is_open() else True,
            "dialog_text": dlg.text() if dlg.is_open() else "",
            "messages": msgs.read_all(),
            "popover_text": msgs.popover_text(),
        }
