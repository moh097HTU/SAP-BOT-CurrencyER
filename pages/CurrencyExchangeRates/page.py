from urllib.parse import urlparse
from datetime import datetime
import os
import time
from typing import Optional
from contextlib import nullcontext

from selenium.common.exceptions import TimeoutException

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


class CurrencyExchangeRatesPage(Page):
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

    def _screenshot(self, tag: str) -> str:
        ts = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        path = os.path.join("logs", f"rates_{tag}_{ts}.png")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            self.driver.save_screenshot(path)
            return path
        except Exception:
            return ""

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

    # -------- App navigation (hardened) --------
    def ensure_in_app(self, max_attempts: int = 2, settle_each: int = 8):
        """
        Guarantee we are on the list report of Currency Exchange Rates app:
          - Deep-link to APP_HASH
          - Wait for UI to settle
          - Force FCL OneColumn if needed
          - Confirm list 'Create' is clickable
        """
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
                return
            except TimeoutException:
                self.driver.execute_script("location.href = arguments[0];", self._app_root_url())
                time.sleep(0.5)

        snap = self._screenshot("ensure_in_app_timeout")
        raise TimeoutException(f"ensure_in_app failed after {attempts} attempts. Screenshot: {snap}")

    def back_to_list(self):
        listbar = ListToolbar(self.driver)
        self.driver.execute_script("location.href = arguments[0];", self._app_root_url())
        wait_ui5_idle(self.driver, timeout=max(self._el()._timeout, 20))
        listbar.wait_create_clickable(timeout=max(60, self._el()._timeout))

    # -------- Internal helpers --------
    def _click_list_create(self, timeout: int | None = None):
        listbar = ListToolbar(self.driver)
        listbar.click_create(timeout or self._el()._timeout)
        wait_ui5_idle(self.driver, timeout=timeout or self._el()._timeout)
        self._wait_not_busy(timeout or self._el()._timeout)

    def _read_last_toast_text(self) -> str:
        return ToastReader(self.driver).read_last()

    # ---- DONE gate via object header ----
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

    # -------- Public: create + submit with 4-stage flow --------
    def create_entry_and_submit(
        self,
        exch_type: str,
        from_ccy: str,
        to_ccy: str,
        valid_from_mmddyyyy: str,
        quotation: str,
        rate_str: str,
        commit_gate=None,   # gate only for the Create/Activate phase
    ) -> dict:
        # Elements
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
        self.ensure_in_app(max_attempts=3, settle_each=8)

        # ---------- local helpers ----------
        def _noop_gate_ctx():
            class _C:
                def __enter__(self): return None
                def __exit__(self, *a): return False
            return _C()

        def _close_msg_popover_if_open():
            try:
                self.driver.execute_script(
                    """
                    try{
                    var b = document.querySelector('.sapMMsgPopoverCloseBtn');
                    if (b && b.offsetParent) { b.click(); return true; }
                    return false;
                    }catch(e){ return false; }
                    """
                )
            except Exception:
                pass

        def _fill_all_fields(prefer_ui5_for_rate: bool = False):
            # ALL PARALLEL-SAFE
            fields.set_plain_input(fields.EXCH_TYPE_INPUT_XPATH, exch_type, press_enter=True)
            fields.set_plain_input(fields.FROM_CCY_INPUT_XPATH, from_ccy, press_enter=True)
            fields.set_plain_input(fields.TO_CCY_INPUT_XPATH, to_ccy, press_enter=True)
            fields.set_plain_input(fields.VALID_FROM_INPUT_XPATH, valid_from_mmddyyyy, press_enter=True)
            quote.set_value(quotation)
            factors.try_set_from("1")
            factors.try_set_to("1")
            if prefer_ui5_for_rate:
                rate.set_via_ui5(rate_str)
                rate.commit(times=1)
            else:
                rate.set_via_typing(rate_str)
                rate.commit(times=2)
            wait_ui5_idle(self.driver, timeout=el._timeout)
            self._wait_not_busy(el._timeout)

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
                # 4) Submit attempt 1 (Create/Activate once)
                first_phase = footer.click_create(clicks=1)
                if first_phase.get("dialogs"):
                    snap = self._screenshot("dialog_open_after_click")
                    return {
                        "status": "dialog_open",
                        "footer_clicks": first_phase.get("clicks", 0),
                        "intermediate_toasts": first_phase.get("toasts", []),
                        "dialog_open": True,
                        "dialog_text": first_phase["dialogs"][-1],
                        "screenshot": snap,
                    }

                # 5) Primary success gate: object header ready
                header_ready = self._wait_object_header_ready(timeout=min(10, max(8, el._timeout)))
                if header_ready:
                    sidecol.close_if_present(timeout=min(12, max(10, el._timeout)))
                    snap = self._screenshot("after_create_closed")
                    return {
                        "status": "created",
                        "footer_clicks": 1,
                        "intermediate_toasts": first_phase.get("toasts", []),
                        "toast": self._read_last_toast_text(),
                        "at_list": True,
                        "dialog_open": False,
                        "dialog_text": "",
                        "screenshot": snap,
                    }

                # 6) Fallback: loop clicking until DONE (handles “kept as draft”)
                loop_res = footer.ensure_created_by_loop_clicking(
                    object_header_ready=lambda: self._wait_object_header_ready(timeout=4),
                    at_list=lambda: listbar.is_at_list(quick=0.8),
                    close_side=lambda: sidecol.close_if_present(timeout=max(8, el._timeout)),
                    total_timeout=max(60, el._timeout + 6),
                    max_clicks=10,  # STRICT: up to 10 presses before giving up
                )
                if loop_res.get("status") in ("created", "dialog_open", "activation_error"):
                    return loop_res  # include activation_error so caller can decide to refill

                # 7) Last fallback (toast or list), then force back to list if still stuck
                final_phase = self._wait_for_success_toast_or_list(timeout=max(el._timeout, 18))
                if not final_phase.get("at_list"):
                    sidecol.close_if_present(timeout=min(12, max(10, el._timeout)))

                snap = self._screenshot("after_create_final")
                if final_phase.get("dialog"):
                    return {
                        "status": "dialog_open",
                        "footer_clicks": 1 + loop_res.get("footer_clicks", 0),
                        "intermediate_toasts": first_phase.get("toasts", []) + loop_res.get("intermediate_toasts", []),
                        "toast": final_phase.get("toast", ""),
                        "dialog_open": True,
                        "dialog_text": final_phase.get("dialog", ""),
                        "screenshot": snap,
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
                        max_clicks=10,
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
                    "screenshot": snap,
                }

        # ---------- 1) Open form ----------
        self._click_list_create(timeout=el._timeout)
        self._screenshot("before_fill")

        # ---------- 2) Fill fields (parallel-safe) ----------
        _fill_all_fields(prefer_ui5_for_rate=False)

        # ---------- 3) Pre-submit validation (client) ----------
        err = validate.collect()
        if err and "greater than zero" in (err or "").lower():
            factors.try_set_from("1")
            factors.try_set_to("1")
            rate.set_via_ui5(rate_str)
            rate.commit(times=1)
            wait_ui5_idle(self.driver, timeout=el._timeout)
            self._wait_not_busy(el._timeout)
            err = validate.collect()  # informational re-check

        # ---------- 4..7) COMMIT under gate ----------
        res = _commit_flow_under_gate()
        if res.get("status") == "activation_error" and _looks_like_required_fields_issue(res.get("messages", [])):
            # Close message popover, REFILL, then try again (still only serializing the commit itself)
            _close_msg_popover_if_open()
            _fill_all_fields(prefer_ui5_for_rate=True)
            res2 = _commit_flow_under_gate()
            if res2.get("status") in ("created", "dialog_open"):
                return res2
            # if still not created, return the second attempt result (more informative)
            return res2
        return res

    def create_rate(
        self,
        exch_type: str,
        from_ccy: str,
        to_ccy: str | None = None,          # expected by your batch
        valid_from_mmddyyyy: str = "",
        quotation: str = "",
        rate_value: str | float = "",
        to_cy: str | None = None,           # legacy/typo alias (optional)
        commit_gate=None,                   # <── NEW: pass-through to submit phase
    ) -> dict:
        # allow both names; prefer to_ccy
        if to_ccy is None and to_cy is not None:
            to_ccy = to_cy
        if to_ccy is None:
            raise TypeError("create_rate() missing required argument: 'to_ccy'")

        return self.create_entry_and_submit(
            exch_type=exch_type,
            from_ccy=from_ccy,
            to_ccy=to_ccy,
            valid_from_mmddyyyy=valid_from_mmddyyyy,
            quotation=quotation,
            rate_str=str(rate_value),
            commit_gate=commit_gate,
        )
