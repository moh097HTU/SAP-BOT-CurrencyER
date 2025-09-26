# pages/CurrencyExchangeRates/page.py

from urllib.parse import urlparse
from datetime import datetime
import os
import time
import re
from typing import Optional
from contextlib import nullcontext

from selenium.common.exceptions import TimeoutException, StaleElementReferenceException
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from core.base import Page, Element
from services.ui import wait_ui5_idle
from .selectors import APP_HASH

# Elements
from .elements.ListToolbar.element import ListToolbar
from .elements.Dialog.element import DialogWatcher
from .elements.Fields.element import Fields
from .elements.Factors.element import Factors
from .elements.Quotation.element import QuotationField
from .elements.Rate.element import ExchangeRateField
from .elements.Footer.element import FooterActions
from .elements.Toast.element import ToastReader
from .elements.Validation.element import ValidationInspector
from .elements.SideColumn.element import SideColumnController
from .elements.Header.element import ObjectHeaderVerifier

# For verify-after-set of Quotation
from .elements.Quotation.selectors import QUOTATION_INNER_INPUT_XPATH

# legacy constant (not used directly; Fields.EXCH_TYPE_INPUT_XPATH is used)
EXCH_TYPE_INPUT_XPATH = ("//input[contains(@id,"
                         "'ExchangeRateTypeForEdit::Field-input-inner')]")

# The exact label we want for the Exchange Rate Type field
TARGET_EXCH_TYPE_LABEL = "M (Standard translation at average rate)"

# --- tiny retry helper (local, non-invasive) ---
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


class CurrencyExchangeRatesPage(Page):
    def __init__(self, driver, root: Optional[str] = None):
        super().__init__(driver, root)
        self._app_ready_fast = False  # quick flag

    def _el(self) -> Element:
        return Element(self.driver)

    # -------- Utilities --------
    def _origin(self) -> str:
        try:
            return self.driver.execute_script("return location.origin;")
        except Exception:
            parsed = urlparse(self.driver.current_url or "")
            return f"{parsed.scheme}://{parsed.netloc}"

    def _app_root_url(self) -> str:
        return f"{self._origin()}/ui?sap-ushell-config=lean{APP_HASH}"

    def _wait_not_busy(self, timeout: int) -> bool:
        end = time.time() + max(1, timeout)
        while time.time() < end:
            try:
                busy = self.driver.execute_script(
                    """
                    try{
                      var core=sap && sap.ui && sap.ui.getCore ? sap.ui.getCore():null;
                      if(core && core.isInitialized && !core.isInitialized()) return true;
                      if(core && core.getUIDirty && core.getUIDirty()) return true;
                      var BI=sap && sap.ui && sap.ui.core && sap.ui.core.BusyIndicator;
                      if(BI && BI.oPopup && BI.oPopup.getOpenState && BI.oPopup.getOpenState() === 'OPEN'){return true;}
                      return false;
                    }catch(e){return false;}
                    """
                )
                if not busy:
                    return True
            except Exception:
                return True
            time.sleep(0.12)
        return False

    # --- EXACTLY set Exchange Rate Type to the full label ---
    def _set_exchange_rate_type_exact(self, fields: Fields, timeout: int = 12) -> dict:
        """
        Hard-sets Exchange Rate Type to the exact UI label:
          M (Standard translation at average rate)

        Returns:
          {"ok": True, "observed": "<value>"} when confirmed exact,
          {"ok": False, "observed": "<value>", "why": "<reason>"} otherwise.
        """
        el = self._el()
        t = max(timeout, el._timeout)

        def _get():
            try:
                return _retry_stale(lambda: (fields.get_input_value(fields.EXCH_TYPE_INPUT_XPATH) or "").strip())
            except Exception:
                return ""

        def _blur(xpath: str):
            try:
                self.driver.execute_script(
                    """
                    try{
                      var el=document.evaluate(arguments[0],document,null,XPathResult.FIRST_ORDERED_NODE_TYPE,null).singleNodeValue;
                      if (el){ el.dispatchEvent(new Event('change',{bubbles:true})); el.blur && el.blur(); }
                    }catch(e){}
                    """,
                    xpath
                )
            except Exception:
                pass

        # fast path — already exact
        cur = _get()
        if cur == TARGET_EXCH_TYPE_LABEL:
            return {"ok": True, "observed": cur}

        # 1) Try simple 'M' + Enter + blur
        try:
            fields.set_plain_input(fields.EXCH_TYPE_INPUT_XPATH, "M", press_enter=True)
        except Exception:
            pass
        _blur(fields.EXCH_TYPE_INPUT_XPATH)
        wait_ui5_idle(self.driver, timeout=t)
        self._wait_not_busy(t)
        cur = _get()
        if cur == TARGET_EXCH_TYPE_LABEL:
            return {"ok": True, "observed": cur}

        # 2) Open value-help and pick exact label
        try:
            vhi_xpath = fields.EXCH_TYPE_INPUT_XPATH.replace("-inner", "-vhi")
            vhi = el.wait_clickable(By.XPATH, vhi_xpath)
            el.js_click(vhi)

            WebDriverWait(self.driver, t).until(
                EC.presence_of_element_located((By.XPATH,
                    "//*[contains(@class,'sapMDialog') or contains(@class,'sapUiMdcValueHelpDialog') or contains(@class,'sapMPopup')]"))
            )
            exact_cell = WebDriverWait(self.driver, t).until(
                EC.element_to_be_clickable((By.XPATH, f"//span[normalize-space(text())='{TARGET_EXCH_TYPE_LABEL}']"))
            )
            el.js_click(exact_cell)

            # If value-help has an OK button, click it
            try:
                ok_btn = WebDriverWait(self.driver, 2).until(
                    EC.element_to_be_clickable((By.XPATH, "//button[.//bdi[normalize-space()='OK'] or .//span[normalize-space()='OK']]"))
                )
                el.js_click(ok_btn)
            except Exception:
                pass
        except Exception:
            pass

        _blur(fields.EXCH_TYPE_INPUT_XPATH)
        wait_ui5_idle(self.driver, timeout=t)
        self._wait_not_busy(t)
        cur = _get()
        if cur == TARGET_EXCH_TYPE_LABEL:
            return {"ok": True, "observed": cur}

        return {"ok": False, "observed": cur, "why": "could_not_select_exact_label"}

    # -------- App navigation (hardened) --------
    def ensure_in_app(self, max_attempts: int = 2, settle_each: int = 8):
        attempts = max(1, max_attempts)
        listbar = ListToolbar(self.driver)
        sidecol = SideColumnController(self.driver)

        for _ in range(attempts):
            cur = (self.driver.current_url or "")
            if APP_HASH.lower() not in cur.lower():
                self.driver.execute_script("location.href = arguments[0];", self._app_root_url())

            wait_ui5_idle(self.driver, timeout=max(self._el()._timeout, settle_each))
            self._wait_not_busy(max(self._el()._timeout, settle_each))

            sidecol.close_if_present(timeout=min(10, max(8, self._el()._timeout)))

            try:
                listbar.wait_create_clickable(timeout=max(60, self._el()._timeout))
                self._app_ready_fast = True
                return
            except TimeoutException:
                self.driver.execute_script("location.href = arguments[0];", self._app_root_url())
                time.sleep(0.5)

        self._app_ready_fast = False
        raise TimeoutException(f"ensure_in_app failed after {attempts} attempts.")

    def ensure_in_app_quick(self):
        if self._app_ready_fast:
            try:
                if ListToolbar(self.driver).is_at_list(quick=1.0):
                    return
            except Exception:
                pass
        self.ensure_in_app(max_attempts=3, settle_each=8)

    def back_to_list(self):
        listbar = ListToolbar(self.driver)
        self.driver.execute_script("location.href = arguments[0];", self._app_root_url())
        wait_ui5_idle(self.driver, timeout=max(self._el()._timeout, 20))
        listbar.wait_create_clickable(timeout=max(60, self._el()._timeout))
        self._app_ready_fast = True

    # -------- Internal helpers --------
    def _click_list_create(self, timeout: int | None = None):
        listbar = ListToolbar(self.driver)
        listbar.click_create(timeout or self._el()._timeout)
        wait_ui5_idle(self.driver, timeout=timeout or self._el()._timeout)
        self._wait_not_busy(timeout or self._el()._timeout)

    def _read_last_toast_text(self) -> str:
        return ToastReader(self.driver).read_last()

    def _wait_object_header_ready(self, timeout: int) -> bool:
        return ObjectHeaderVerifier(self.driver).wait_ready(timeout=timeout)

    def _wait_for_success_toast_or_list(self, timeout: int) -> dict:
        listbar = ListToolbar(self.driver)
        dlg = DialogWatcher(self.driver)
        end = time.time() + max(timeout, self._el()._timeout)
        info = {"toast": "", "dialog": "", "at_list": False}
        while time.time() < end:
            if dlg.is_open():
                info["dialog"] = dlg.text() or "Dialog open (no text captured)."
                return info
            txt = ToastReader(self.driver).read_last()
            if txt:
                info["toast"] = txt
                lt = txt.lower()
                if any(k in lt for k in ("created", "saved", "activated", "has been created", "successfully")):
                    return info
            try:
                listbar.wait_create_clickable(timeout=0.8)
                info["at_list"] = True
                return info
            except Exception:
                pass
            time.sleep(0.18)
        return info

    # -------- SOFT guard: ensure type contains 'M' (do not abort) --------
    def _soft_ensure_exch_type_contains_M(self, fields: Fields, desired_exch_type: str) -> dict:
        """
        Ensure the Exchange Rate Type *contains* 'M' BEFORE clicking Create,
        but do NOT abort the row pre-commit.
        """
        def _get():
            try:
                return _retry_stale(lambda: (fields.get_input_value(fields.EXCH_TYPE_INPUT_XPATH) or "").strip())
            except Exception:
                return ""

        cur = _get()
        if "m" in cur.lower():
            return {"ok": True, "observed": cur}

        # corrective retype
        try:
            fields.set_plain_input(fields.EXCH_TYPE_INPUT_XPATH, desired_exch_type, press_enter=True)
        except Exception:
            pass
        # explicit blur to fire change bindings
        try:
            self.driver.execute_script(
                """
                try{
                  var el=document.evaluate(arguments[0],document,null,XPathResult.FIRST_ORDERED_NODE_TYPE,null).singleNodeValue;
                  if (el){ el.dispatchEvent(new Event('change',{bubbles:true})); el.blur&&el.blur(); }
                }catch(e){}
                """,
                fields.EXCH_TYPE_INPUT_XPATH
            )
        except Exception:
            pass

        wait_ui5_idle(self.driver, timeout=self._el()._timeout)
        self._wait_not_busy(self._el()._timeout)

        cur2 = _get()
        return {"ok": ("m" in cur2.lower()), "observed": cur2}

    # ---------------- NEW helpers for your policy ----------------
    def _detect_lock_info(self, text: str) -> dict | None:
        if not text:
            return None
        low = text.lower()
        if "locked by user" in low and "table" in low and "tcurr" in low:
            m = re.search(r"Table\s+(\w+)\s+is\s+locked\s+by\s+user\s+([A-Za-z0-9_]+)", text, re.IGNORECASE)
            table = None
            owner = None
            if m:
                table = m.group(1)
                owner = m.group(2)
            return {"table": table or "TCURR", "owner": owner or ""}
        return None

    def _is_required_fields_dialog(self, s: str) -> bool:
        return "fill out all required entry fields" in (s or "").lower()

    def _is_duplicate_exists(self, s: str) -> bool:
        low = (s or "").lower()
        return ("exchange rate" in low) and ("already exists in the system" in low)

    # -------- Public: create + submit --------
    def create_entry_and_submit(
        self,
        exch_type: str,
        from_ccy: str,
        to_ccy: str,
        valid_from_ddmmyyyy: str,     # IMPORTANT: pass DD.MM.YYYY
        quotation: str,
        rate_str: str,
        commit_gate=None,
    ) -> dict:
        fields = Fields(self.driver)
        factors = Factors(self.driver)
        quote = QuotationField(self.driver)
        rate = ExchangeRateField(self.driver)
        footer = FooterActions(self.driver)
        listbar = ListToolbar(self.driver)
        dlg = DialogWatcher(self.driver)
        sidecol = SideColumnController(self.driver)
        validate = ValidationInspector(self.driver)

        el = self._el()

        # QUICK ensure to avoid heavy waits on every item
        self.ensure_in_app_quick()

        # ---------- local helpers ----------
        def _noop_gate_ctx():
            class _C:
                def __enter__(self): return None
                def __exit__(self, *a): return False
            return _C()

        def _verify_or_retype(xpath: str, expected: str) -> None:
            if expected is None:
                return
            got = (fields.get_input_value(xpath) or "").strip()
            if got.lower() != (expected or "").strip().lower():
                fields.set_plain_input(xpath, expected, press_enter=True)
                _ = fields.get_input_value(xpath)

        def _verify_quotation(expected: str) -> None:
            try:
                cur = _retry_stale(lambda: (self.driver.find_element(By.XPATH, QUOTATION_INNER_INPUT_XPATH).get_attribute("value") or "").strip())
            except Exception:
                cur = ""
            if cur.lower() != (expected or "").strip().lower():
                quote.set_value(expected)

        def _fill_all_fields(prefer_ui5_for_rate: bool = False):
            # 1) Exchange Rate Type
            fields.set_plain_input(fields.EXCH_TYPE_INPUT_XPATH, exch_type, press_enter=True)
            _verify_or_retype(fields.EXCH_TYPE_INPUT_XPATH, exch_type)

            # 2) From Currency
            fields.set_plain_input(fields.FROM_CCY_INPUT_XPATH, from_ccy, press_enter=True)
            _verify_or_retype(fields.FROM_CCY_INPUT_XPATH, from_ccy)

            # 3) To Currency
            fields.set_plain_input(fields.TO_CCY_INPUT_XPATH, to_ccy, press_enter=True)
            _verify_or_retype(fields.TO_CCY_INPUT_XPATH, to_ccy)

            # 4) Valid From — **DD.MM.YYYY**
            fields.set_plain_input(fields.VALID_FROM_INPUT_XPATH, valid_from_ddmmyyyy, press_enter=True)
            _verify_or_retype(fields.VALID_FROM_INPUT_XPATH, valid_from_ddmmyyyy)

            # 5) Quotation
            quote.set_value(quotation)
            _verify_quotation(quotation)

            # 6) Factors and Rate
            factors.try_set_from("1")
            factors.try_set_to("1")
            if prefer_ui5_for_rate:
                rate.set_via_ui5(rate_str)
                rate.commit(times=1)
            else:
                rate.set_via_typing(rate_str)
                rate.commit(times=2)

        def _looks_like_required_fields_issue(msgs: list[dict]) -> bool:
            if not msgs:
                return False
            blob = " | ".join(
                f"{(m.get('message') or '')} {m.get('description') or ''}".lower()
                for m in msgs
            )
            keys = (
                "fill out all required",
                "required entry fields",
                "required field",
                "mandatory field",
                "exchange rate type",
                "from currency",
            )
            return any(k in blob for k in keys)

        def _commit_flow_under_gate() -> dict:
            gate_ctx = commit_gate() if callable(commit_gate) else _noop_gate_ctx()
            with gate_ctx:
                first_phase = footer.click_create(clicks=1)

                header_ready = self._wait_object_header_ready(timeout=min(10, max(8, el._timeout)))
                if header_ready:
                    sidecol.close_if_present(timeout=min(12, max(10, el._timeout)))
                    return {
                        "status": "created",
                        "footer_clicks": 1,
                        "intermediate_toasts": first_phase.get("toasts", []),
                        "toast": self._read_last_toast_text(),
                        "at_list": True,
                        "dialog_open": False,
                        "dialog_text": "",
                    }

                loop_res = footer.ensure_created_by_loop_clicking(
                    object_header_ready=lambda: self._wait_object_header_ready(timeout=4),
                    at_list=lambda: listbar.is_at_list(quick=0.8),
                    close_side=lambda: sidecol.close_if_present(timeout=max(8, el._timeout)),
                    total_timeout=max(35, el._timeout),
                    max_clicks=5,
                )
                if loop_res.get("status") in ("created", "dialog_open", "activation_error"):
                    return loop_res

                final_phase = self._wait_for_success_toast_or_list(timeout=max(el._timeout, 18))
                if not final_phase.get("at_list"):
                    sidecol.close_if_present(timeout=min(12, max(10, el._timeout)))

                if final_phase.get("dialog"):
                    return {
                        "status": "dialog_open",
                        "footer_clicks": 1 + loop_res.get("footer_clicks", 0),
                        "intermediate_toasts": first_phase.get("toasts", []) + loop_res.get("intermediate_toasts", []),
                        "toast": final_phase.get("toast", ""),
                        "dialog_open": True,
                        "dialog_text": final_phase.get("dialog", ""),
                    }

                status_guess = "created" if (
                    final_phase.get("at_list")
                    or (final_phase.get("toast") and any(k in final_phase.get("toast", "").lower()
                        for k in ("created", "activated", "successfully")))
                ) else "unknown"

                if status_guess != "created":
                    strict = footer.ensure_created_by_loop_clicking(
                        object_header_ready=lambda: self._wait_object_header_ready(timeout=4),
                        at_list=lambda: listbar.is_at_list(quick=0.8),
                        close_side=lambda: sidecol.close_if_present(timeout=max(8, el._timeout)),
                        total_timeout=max(30, el._timeout),
                        max_clicks=5,
                    )
                    if strict.get("status") == "created":
                        return strict

                return {
                    "status": status_guess,
                    "footer_clicks": 1 + loop_res.get("footer_clicks", 0),
                    "intermediate_toasts": first_phase.get("toasts", []) + loop_res.get("intermediate_toasts", []),
                    "toast": final_phase.get("toast", ""),
                    "at_list": True,
                    "dialog_open": False,
                    "dialog_text": "",
                }

        # 1) Open form
        self._click_list_create(timeout=el._timeout)

        # 2) Fill fields (DD.MM.YYYY is passed straight through)
        _fill_all_fields(prefer_ui5_for_rate=False)

        # 2.5) SOFT GUARD: ensure Exchange Rate Type *contains* "M"
        m_check = self._soft_ensure_exch_type_contains_M(fields, exch_type)

        # 3) Pre-submit validation (client)
        err = ValidationInspector(self.driver).collect()
        if err and "greater than zero" in (err or "").lower():
            Factors(self.driver).try_set_from("1")
            Factors(self.driver).try_set_to("1")
            ExchangeRateField(self.driver).set_via_ui5(rate_str)
            ExchangeRateField(self.driver).commit(times=1)
            err = ValidationInspector(self.driver).collect()

        # 4) COMMIT attempt
        res = _commit_flow_under_gate()
        status = (res.get("status") or "").lower()

        # 5) Post-commit note if M was missing pre-commit
        if not m_check.get("ok", True):
            res.setdefault("notes", {})
            res["notes"]["exch_type_missing_M_precommit"] = True
            res["notes"]["observed_exch_type"] = m_check.get("observed", "")

        # --- Build a combined message blob for policy checks
        msgs_from_res = res.get("messages", []) or []
        joined_msgs = " | ".join(f"{(m.get('message') or '')} {m.get('description') or ''}".strip() for m in msgs_from_res)
        joined_all = " | ".join([res.get("dialog_text") or "", joined_msgs]).strip()

        # *** NEW *** also read the Message Popover (this is where "already exists" lives)
        pop_msgs = []
        try:
            pop_msgs = footer.open_and_read_messages(timeout=max(6, el._timeout))
        except Exception:
            pop_msgs = []
        if pop_msgs:
            # add to the joined blob for the same downstream checks
            joined_all = " | ".join(filter(None, [joined_all, " | ".join(pop_msgs)]))
        # close popover (so footer buttons stay clickable)
        try:
            footer.close_message_popover_if_open(timeout=3)
        except Exception:
            pass

        # === POLICY REMAP ===
        # TCURR lock anywhere → Pending (not Locked)
        lock = self._detect_lock_info(joined_all)
        if lock:
            try: DialogWatcher(self.driver).close(timeout=1.0)
            except Exception: pass
            SideColumnController(self.driver).close_if_present(timeout=min(12, max(10, el._timeout)))
            try: self.back_to_list()
            except Exception: pass
            return {
                "status": "pending",
                "dialog_open": False,
                "dialog_text": res.get("dialog_text", ""),
                "notes": {
                    "lock_table": lock.get("table", "TCURR"),
                    "lock_owner": lock.get("owner", ""),
                    "reason": "table_lock_tcurr"
                }
            }

        # Duplicate exists → Skipped **AND discard draft** (new behavior)
        # keep your existing detector, but now it sees popover text too
        if self._is_duplicate_exists(joined_all) or ("already exists" in joined_all.lower()):
            # close any popover/dialog so the footer is clickable
            try: DialogWatcher(self.driver).close(timeout=1.2)
            except Exception: pass
            try: footer.close_message_popover_if_open(timeout=2)
            except Exception: pass

            # attempt to discard the draft quietly
            try:
                _discarded = footer.discard_draft(timeout=max(8, el._timeout))
            except Exception:
                _discarded = False

            # close side column (no-op if already closed) and go back to list
            SideColumnController(self.driver).close_if_present(timeout=min(12, max(10, el._timeout)))
            try: self.back_to_list()
            except Exception: pass

            out = {
                "status": "skipped",
                "dialog_open": False,
                "dialog_text": res.get("dialog_text", ""),
                "notes": {
                    "already_existed": True,
                    "draft_discarded": bool(_discarded),
                    "message_count": len(pop_msgs) if pop_msgs else len(msgs_from_res),
                },
            }
            return out

        # Created passes through as Created (runner/worker mapping unchanged)
        if status == "created":
            return res

        # Unknown: re-queue → map to 'pending'
        if status == "unknown":
            res["status"] = "pending"
            return res

        # anything else → return as-is (error/activation_error/dialog_open, etc.)
        return res

    def create_rate(
        self,
        exch_type: str,
        from_ccy: str,
        to_ccy: str | None = None,
        valid_from_mmddyyyy: str = "",
        quotation: str = "",
        rate_value: str | float = "",
        to_cy: str | None = None,
        commit_gate=None,
    ) -> dict:
        """
        NOTE: pass date in **DD.MM.YYYY**. We DO NOT convert here.
        services.schemas.ExchangeRateItem already normalizes to DD.MM.YYYY.
        """
        if to_ccy is None and to_cy is not None:
            to_ccy = to_cy
        if to_ccy is None:
            raise TypeError("create_rate() missing required argument: 'to_ccy'")

        valid_from_ddmmyyyy = valid_from_mmddyyyy

        return self.create_entry_and_submit(
            exch_type=exch_type,
            from_ccy=from_ccy,
            to_ccy=to_ccy,
            valid_from_ddmmyyyy=valid_from_ddmmyyyy,   # typed as-is
            quotation=quotation,
            rate_str=str(rate_value),
            commit_gate=commit_gate,
        )
