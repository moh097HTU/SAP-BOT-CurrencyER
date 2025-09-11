import time
from typing import Callable, Dict

from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException

from core.base import Element, fluent_wait
from services.ui import wait_ui5_idle
from ..Dialog.element import DialogWatcher
from ..Toast.element import ToastReader
from ..Messages.element import Ui5Messages
from .selectors import (
    ACTIVATE_CREATE_BTN_XPATH,
    FORM_CREATE_OR_SAVE_BTN_XPATH,
    ACTIVATE_CREATE_BTN_CSS,
    HEADER_TITLE_ID_SUFFIX,
    EDIT_BTN_ID_SUFFIX,
    DISCARD_BTN_ID_SUFFIX,
)

class FooterActions(Element):
    """
    Submit logic with:
      - first attempt click
      - loop clicking with DOM/MessageManager checks
    """

    EXTRA_SETTLE_SEC = 2.0  # hard settle after every press

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
                el = self.driver.find_element(By.ID, act_id)
                try:
                    self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
                except Exception:
                    pass

                if self._really_clickable(act_id):
                    try:
                        el.click()
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
                btn.click()
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

    # ---------- DOM success predicate (from your HTML) ----------

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

    # ---------- Public API: attempt once ----------

    def click_create(self, clicks: int = 1) -> dict:
        """
        One-shot (or limited) Create/Activate click(s), collecting toast & dialog.
        """
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
            wait_ui5_idle(self.driver, timeout=max(self._timeout, 10))
            time.sleep(self.EXTRA_SETTLE_SEC)

            try:
                txt = reader.read_last()
                if txt:
                    info["toasts"].append(txt)
            except Exception:
                pass

            if dlg.is_open():
                info["dialogs"].append(dlg.text() or "")
                break

        return info

    # ---------- Fallback loop (fluent) ----------

    def ensure_created_by_loop_clicking(
        self,
        object_header_ready: Callable[[], bool],
        at_list: Callable[[], bool],
        close_side: Callable[[], bool],
        max_clicks: int = 10,
        total_timeout: int = 60,
    ) -> Dict:
        dlg = DialogWatcher(self.driver)
        reader = ToastReader(self.driver)
        msgs = Ui5Messages(self.driver)

        end = time.time() + max(total_timeout, self._timeout)
        clicks = 0
        toasts = []
        msgs.clear()

        while clicks < max_clicks and time.time() < end:
            if dlg.is_open():
                return {
                    "status": "dialog_open",
                    "dialog_open": True,
                    "dialog_text": dlg.text(),
                    "footer_clicks": clicks,
                    "intermediate_toasts": toasts,
                    "messages": msgs.read_all(),
                }

            # Backend/UI5 message errors?
            if msgs.has_errors():
                return {
                    "status": "activation_error",
                    "dialog_open": False,
                    "dialog_text": "",
                    "footer_clicks": clicks,
                    "intermediate_toasts": toasts,
                    "messages": msgs.errors(),
                }

            # Already activated or at list?
            if self._activated_dom() or object_header_ready() or at_list():
                close_side()
                return {
                    "status": "created",
                    "dialog_open": False,
                    "dialog_text": "",
                    "footer_clicks": clicks,
                    "intermediate_toasts": toasts,
                    "messages": msgs.read_all(),
                }

            # Press
            if self._press_activate_best_effort():
                clicks += 1
                wait_ui5_idle(self.driver, timeout=min(6, self._timeout))
                time.sleep(self.EXTRA_SETTLE_SEC)

            # Toasts (telemetry & success keywords)
            try:
                t = reader.read_last()
                if t:
                    toasts.append(t)
                    lt = (t or "").lower()
                    if any(k in lt for k in ("created", "saved", "activated", "has been created", "successfully")):
                        close_side()
                        return {
                            "status": "created",
                            "dialog_open": False,
                            "dialog_text": "",
                            "footer_clicks": clicks,
                            "intermediate_toasts": toasts,
                            "messages": msgs.read_all(),
                        }
            except Exception:
                pass

            time.sleep(0.2)

        if not at_list():
            close_side()

        return {
            "status": "created"
            if at_list() or object_header_ready() or self._activated_dom()
            else "unknown",
            "footer_clicks": clicks,
            "intermediate_toasts": toasts,
            "dialog_open": False if not dlg.is_open() else True,
            "dialog_text": dlg.text() if dlg.is_open() else "",
            "messages": msgs.read_all(),
        }
