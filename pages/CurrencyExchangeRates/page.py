from urllib.parse import urlparse
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
import os
import time

from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import (
    StaleElementReferenceException,
    ElementClickInterceptedException,
    TimeoutException,
)

from core.base import Page, Element
from services.ui import wait_ui5_idle
from .selectors import (
    APP_HASH,
    CREATE_BUTTON_XPATH,
    EXCH_TYPE_INPUT_XPATH,
    FROM_CCY_INPUT_XPATH,
    TO_CCY_INPUT_XPATH,
    VALID_FROM_INPUT_XPATH,
    QUOTATION_INNER_INPUT_XPATH,
    QUOTATION_ARROW_BTN_XPATH,
    QUOTATION_OPTION_BY_TEXT_XPATH,
    EXCH_RATE_INPUT_XPATH,
    EXCH_RATE_INPUT_FALLBACK_XPATH,
    FROM_FACTOR_BY_LABEL_XPATH,
    TO_FACTOR_BY_LABEL_XPATH,
    FORM_CREATE_OR_SAVE_BTN_XPATH,
    ACTIVATE_CREATE_BTN_XPATH,
    MESSAGE_TOAST_CSS,
    ANY_INVALID_INPUT_XPATH,
    ANY_ERROR_WRAPPER_XPATH,
    DIALOG_ROOT_CSS,
    # NEW
    OBJECT_HEADER_CONTENT_XPATH,
    OBJECT_HEADER_RATE_VALUE_XPATH,
    CLOSE_COLUMN_BTN_XPATH,
)

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

    # -------- Dialog detection (read only; never close) --------
    def _dialog_open(self) -> bool:
        try:
            return bool(self.driver.execute_script(
                "var a=document.querySelectorAll(arguments[0]);"
                "for(var i=a.length-1;i>=0;i--){var el=a[i];"
                "var s=window.getComputedStyle(el);"
                "if(s && s.display!=='none' && s.visibility!=='hidden' && el.offsetWidth>0 && el.offsetHeight>0){return true;}}"
                "return false;", DIALOG_ROOT_CSS
            ))
        except Exception:
            return False

    def _capture_dialog_text(self) -> str:
        try:
            txt = self.driver.execute_script(
                "var a=document.querySelectorAll(arguments[0]);"
                "for(var i=a.length-1;i>=0;i--){var el=a[i];"
                "var s=window.getComputedStyle(el);"
                "if(s && s.display!=='none' && s.visibility!=='hidden' && el.offsetWidth>0 && el.offsetHeight>0){"
                "  return (el.innerText||el.textContent||'').trim();}}"
                "return '';", DIALOG_ROOT_CSS
            )
            return (txt or "").strip()
        except Exception:
            return ""

    # -------- App navigation --------
    def ensure_in_app(self):
        try:
            cur = self.driver.current_url or ""
        except Exception:
            cur = ""
        if APP_HASH.lower() not in cur.lower():
            self.driver.execute_script("location.href = arguments[0];", self._app_root_url())
            wait_ui5_idle(self.driver, timeout=Element(self.driver)._timeout)
        el = self._el()
        WebDriverWait(self.driver, max(el._timeout, 20)).until(
            EC.element_to_be_clickable((By.XPATH, CREATE_BUTTON_XPATH))
        )

    def back_to_list(self):
        self.driver.execute_script("location.href = arguments[0];", self._app_root_url())
        el = self._el()
        wait_ui5_idle(self.driver, timeout=max(el._timeout, 20))
        WebDriverWait(self.driver, max(el._timeout, 20)).until(
            EC.element_to_be_clickable((By.XPATH, CREATE_BUTTON_XPATH))
        )

    # LIST → click Create
    def _click_list_create(self, timeout: int | None = None):
        el = self._el()
        btn = el.wait_clickable(By.XPATH, CREATE_BUTTON_XPATH)
        try:
            btn.click()
        except Exception:
            el.js_click(btn)
        wait_ui5_idle(self.driver, timeout=timeout or el._timeout)
        self._wait_not_busy(timeout or el._timeout)

    # -------- Helpers: robust field set --------
    def _hard_clear(self, web_el):
        for fn in (
            lambda: web_el.clear(),
            lambda: web_el.send_keys(Keys.CONTROL, "a"),
            lambda: web_el.send_keys(Keys.DELETE),
            lambda: self.driver.execute_script(
                "arguments[0].value='';"
                "arguments[0].dispatchEvent(new Event('input',{bubbles:true}));"
                "arguments[0].dispatchEvent(new Event('change',{bubbles:true}));", web_el),
        ):
            try: fn()
            except Exception: pass

    def _set_plain_input(self, xpath: str, value: str, press_enter: bool = False):
        el = self._el()
        inp = el.wait_visible(By.XPATH, xpath)
        self._hard_clear(inp)
        if value is not None:
            inp.send_keys(value)
        if press_enter:
            try: inp.send_keys(Keys.ENTER)
            except Exception: pass
        try: inp.send_keys(Keys.TAB)
        except Exception: pass

    def _try_set_factor_by_label(self, label_xpath: str, value: str = "1"):
        try:
            inp = self.driver.find_element(By.XPATH, label_xpath)
        except Exception:
            return False
        try:
            self._hard_clear(inp)
            inp.send_keys(value)
            try: inp.send_keys(Keys.TAB)
            except Exception: pass
            wait_ui5_idle(self.driver, timeout=self._el()._timeout)
            return True
        except Exception:
            return False

    # -------- Quotation --------
    def _set_quotation_value(self, value: str):
        el = self._el()
        wait = WebDriverWait(self.driver, max(el._timeout, 20))
        inp = el.wait_visible(By.XPATH, QUOTATION_INNER_INPUT_XPATH)
        try:
            inp.click()
        except Exception:
            el.js_click(inp)

        self._hard_clear(inp)

        inp.send_keys(value)
        inp.send_keys(Keys.ENTER)
        inp.send_keys(Keys.TAB)
        wait_ui5_idle(self.driver, timeout=el._timeout)

        cur = (inp.get_attribute("value") or "").strip()
        if cur.lower() != value.strip().lower():
            try:
                arrow = wait.until(EC.element_to_be_clickable((By.XPATH, QUOTATION_ARROW_BTN_XPATH)))
                try: arrow.click()
                except Exception: el.js_click(arrow)
            except Exception:
                try: inp.send_keys(Keys.ALT, Keys.DOWN)
                except Exception: pass
            wait_ui5_idle(self.driver, timeout=el._timeout)
            opt_xpath = QUOTATION_OPTION_BY_TEXT_XPATH.format(TEXT=value.strip())
            option = wait.until(EC.element_to_be_clickable((By.XPATH, opt_xpath)))
            try: option.click()
            except Exception: el.js_click(option)
            wait_ui5_idle(self.driver, timeout=el._timeout)

    # -------- Locale handling for rate typing --------
    def _ui_lang_tag(self) -> str:
        try:
            return self.driver.execute_script(
                """
                try{
                  var c=sap && sap.ui && sap.ui.getCore && sap.ui.getCore().getConfiguration && sap.ui.getCore().getConfiguration();
                  if(!c) return (navigator.language || 'en-US');
                  if (c.getLanguageTag) return c.getLanguageTag();
                  if (c.getLanguage)    return c.getLanguage();
                  return (navigator.language || 'en-US');
                }catch(e){ return (navigator.language || 'en-US'); }
                """
            ) or "en-US"
        except Exception:
            return "en-US"

    def _format_rate_locale(self, num: Decimal) -> str:
        q = num.quantize(Decimal("0.00001"), rounding=ROUND_HALF_UP)
        lang = self._ui_lang_tag()
        try:
            from babel.numbers import format_decimal
            return format_decimal(q, format="0.00000", locale=(lang or "en-US").replace("-", "_"))
        except Exception:
            try:
                return self.driver.execute_script(
                    """
                    try{
                      var val = Number(arguments[0]);
                      var lang = arguments[1] || (navigator.language || 'en-US');
                      if (!isFinite(val)) return '';
                      return new Intl.NumberFormat(lang,
                               {minimumFractionDigits:5, maximumFractionDigits:5, useGrouping:false}
                              ).format(val);
                    }catch(e){ return String(arguments[0]); }
                    """,
                    float(q), lang
                )
            except Exception:
                return f"{q:.5f}"

    def _find_rate_input(self):
        el = self._el()
        try:
            return el.wait_visible(By.XPATH, EXCH_RATE_INPUT_XPATH)
        except Exception:
            pass
        try:
            return el.wait_visible(By.XPATH, EXCH_RATE_INPUT_FALLBACK_XPATH)
        except Exception:
            raise RuntimeError("Exchange Rate input not found (primary nor fallback).")

    def _commit_rate_field(self, times: int = 1):
        el = self._el()
        inp = self._find_rate_input()
        try:
            self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", inp)
        except Exception:
            pass
        try:
            inp.click()
        except Exception:
            el.js_click(inp)

        try:
            ac = ActionChains(self.driver)
            for _ in range(max(1, times)):
                ac.send_keys(Keys.ENTER).pause(0.05)
            ac.send_keys(Keys.TAB)
            ac.perform()
        except Exception:
            try:
                inp.send_keys(Keys.ENTER); inp.send_keys(Keys.TAB)
            except Exception: pass

        # JS fallback to trigger UI5 hooks
        try:
            inner_id = inp.get_attribute("id") or ""
            self.driver.execute_script(
                """
                try{
                  var el=arguments[0], innerId=arguments[1];
                  if(el){
                      el.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}));
                      el.dispatchEvent(new KeyboardEvent('keyup',{key:'Enter',bubbles:true}));
                      el.dispatchEvent(new Event('change',{bubbles:true}));
                      el.dispatchEvent(new Event('blur',{bubbles:true}));
                  }
                  var ctrlId = innerId && innerId.endsWith('-inner') ? innerId.slice(0,-6) : innerId;
                  var ctrl=sap && sap.ui && sap.ui.getCore ? sap.ui.getCore().byId(ctrlId) : null;
                  if(ctrl){
                      if (typeof ctrl.onsapenter === 'function') { ctrl.onsapenter(); }
                      if (typeof ctrl.fireChange === 'function') { ctrl.fireChange({ value: ctrl.getValue ? ctrl.getValue() : undefined }); }
                  }
                }catch(e){}
                """,
                inp, inner_id
            )
        except Exception:
            pass

        wait_ui5_idle(self.driver, timeout=el._timeout)
        self._wait_not_busy(el._timeout)

    def _set_rate_value_via_typing(self, rate_val: str | float | Decimal):
        num = Decimal(str(rate_val))
        if num <= 0:
            raise ValueError("rate_val must be > 0")
        s = self._format_rate_locale(num)
        inp = self._find_rate_input()
        self._hard_clear(inp)
        inp.send_keys(s)
        try: inp.send_keys(Keys.TAB)
        except Exception: pass
        wait_ui5_idle(self.driver, timeout=self._el()._timeout)
        self._wait_not_busy(self._el()._timeout)

    # ---- Fallback UI5 setValue ----
    def _set_rate_value_ui5(self, rate_val: str | float | Decimal):
        el = self._el()
        inp = self._find_rate_input()
        inner_id = inp.get_attribute("id")
        if not inner_id:
            raise RuntimeError("Exchange Rate input has no DOM id")

        res = self.driver.execute_script(
            """
            try{
              var innerId=arguments[0], num=Number(String(arguments[1]).replace(',','.'));
              if(!isFinite(num) || num<=0){ return {ok:false, reason:'nonpositive'}; }
              var ctrlId = innerId.endsWith('-inner') ? innerId.slice(0,-6) : innerId;
              var ctrl = sap && sap.ui && sap.ui.getCore ? sap.ui.getCore().byId(ctrlId) : null;
              var fmt = (sap && sap.ui && sap.ui.core && sap.ui.core.format && sap.ui.core.format.NumberFormat)
                        ? sap.ui.core.format.NumberFormat.getFloatInstance({maxFractionDigits:5,minFractionDigits:5,groupingEnabled:false})
                        : null;
              var s = fmt ? fmt.format(num) : num.toFixed(5);

              if(ctrl && ctrl.setValue){
                  ctrl.setValue(s);
                  if (ctrl.fireLiveChange) ctrl.fireLiveChange({ value: s });
                  if (ctrl.fireChange)     ctrl.fireChange({ value: s });
              }
              var el = document.getElementById(innerId);
              if(el){
                  el.focus();
                  el.value = s;
                  el.dispatchEvent(new Event('input',{bubbles:true}));
                  el.dispatchEvent(new Event('change',{bubbles:true}));
              }
              var parsed = fmt ? fmt.parse(s) : Number(s.replace(',','.'));
              return {ok:(typeof parsed==='number' && parsed>0), shown:s, parsed:parsed};
            }catch(e){ return {ok:false, reason:String(e)}; }
            """,
            inner_id, str(rate_val)
        )
        wait_ui5_idle(self.driver, timeout=el._timeout)
        self._wait_not_busy(el._timeout)
        if not res or not res.get("ok"):
            snap = self._screenshot("rate_set_failed")
            raise RuntimeError(f"Could not set Exchange Rate via UI5. Result={res}. Screenshot: {snap}")

    # -------- Observability helpers --------
    def _has_validation_errors(self) -> str | None:
        try:
            bad_inputs = self.driver.find_elements(By.XPATH, ANY_INVALID_INPUT_XPATH)
            if bad_inputs:
                messages = []
                for el_ in bad_inputs:
                    try:
                        err_id = el_.get_attribute("aria-errormessage") or ""
                        msg = self.driver.execute_script(
                            "var id=arguments[0];"
                            "var n=id?document.getElementById(id):null;"
                            "return n? (n.innerText || n.textContent || '').trim():'';", err_id)
                        if msg: messages.append(msg)
                    except Exception:
                        continue
                if messages: return "; ".join(sorted(set(messages)))
                return f"{len(bad_inputs)} invalid field(s)."
            wrappers = self.driver.find_elements(By.XPATH, ANY_ERROR_WRAPPER_XPATH)
            if wrappers: return f"{len(wrappers)} field wrapper(s) in error state."
        except Exception:
            pass
        return None

    def _wait_for_success_toast_or_list(self, timeout: int) -> dict:
        el = self._el()
        end = time.time() + max(timeout, el._timeout)
        info = {"toast": "", "dialog": "", "at_list": False}
        while time.time() < end:
            if self._dialog_open():
                info["dialog"] = self._capture_dialog_text() or "Dialog open (no text captured)."
                return info
            try:
                txt = self.driver.execute_script(
                    "var nodes=document.querySelectorAll(arguments[0]);"
                    "if(!nodes||nodes.length===0) return '';"
                    "var t=nodes[nodes.length-1];"
                    "return (t.innerText||t.textContent||'').trim();",
                    MESSAGE_TOAST_CSS,
                )
                if isinstance(txt, str) and txt:
                    info["toast"] = txt
            except Exception:
                pass
            try:
                _ = WebDriverWait(self.driver, 0.8).until(
                    EC.element_to_be_clickable((By.XPATH, CREATE_BUTTON_XPATH))
                )
                info["at_list"] = True
                return info
            except Exception:
                pass
            time.sleep(0.18)
        return info

    # ---- DONE gate: wait until the Object Page header is really there ----
    def _wait_object_header_ready(self, timeout: int) -> bool:
        t0 = time.time()
        try:
            WebDriverWait(self.driver, min(6, timeout)).until(
                EC.presence_of_element_located((By.XPATH, OBJECT_HEADER_CONTENT_XPATH))
            )
        except TimeoutException:
            return False
        # Make sure it actually shows values (like the Exchange Rate text)
        while time.time() - t0 < min(timeout, 10):
            try:
                span = self.driver.find_element(By.XPATH, OBJECT_HEADER_RATE_VALUE_XPATH)
                if (span.text or "").strip():
                    return True
            except Exception:
                pass
            time.sleep(0.15)
        return False

    # ---- Close side column (X) or force FCL → OneColumn; fallback to list deep-link ----
    def _close_side_column_if_present(self, timeout: int | None = None) -> bool:
        el = self._el()
        t = timeout or max(el._timeout, 20)

        # If we're already back to list, done
        try:
            WebDriverWait(self.driver, 1.0).until(EC.element_to_be_clickable((By.XPATH, CREATE_BUTTON_XPATH)))
            return True
        except Exception:
            pass

        # 1) Try DOM close button (cover multiple ids/variants)
        try:
            btn = WebDriverWait(self.driver, min(5, t)).until(
                EC.element_to_be_clickable((By.XPATH, CLOSE_COLUMN_BTN_XPATH))
            )
            try:
                self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
            except Exception:
                pass
            try:
                btn.click()
            except Exception:
                el.js_click(btn)
            wait_ui5_idle(self.driver, timeout=min(6, t))
            self._wait_not_busy(min(6, t))
        except TimeoutException:
            # 2) JS sweep: click any closeColumn* button
            try:
                did = self.driver.execute_script(
                    """
                    try{
                      var q = document.querySelectorAll(
                        "button[id$='--closeColumn'],button[id$='--closeColumnBtn'],button[id*='closeColumn']"
                      );
                      for (var i=q.length-1;i>=0;i--){
                        var b=q[i];
                        var cs=window.getComputedStyle(b);
                        if(b && b.offsetParent && cs.visibility!=='hidden' && cs.display!=='none'){ b.click(); return 'clicked-dom'; }
                      }
                      return 'none';
                    }catch(e){ return 'err:'+e; }
                    """
                )
            except Exception:
                did = "err"
            wait_ui5_idle(self.driver, timeout=2)
            self._wait_not_busy(2)

            # 3) UI5 control path: set FCL layout to OneColumn
            if did != "clicked-dom":
                try:
                    mode = self.driver.execute_script(
                        """
                        try{
                          var core=sap && sap.ui && sap.ui.getCore && sap.ui.getCore();
                          if(!core) return 'no-core';
                          var all = core && core.mElements ? Object.values(core.mElements) : [];
                          var fcl=null, name='';
                          for (var i=0;i<all.length;i++){
                            var c=all[i];
                            try{
                              name=c.getMetadata && c.getMetadata().getName && c.getMetadata().getName();
                              if(name==='sap.f.FlexibleColumnLayout'){ fcl=c; break; }
                            }catch(e){}
                          }
                          if(fcl && fcl.setLayout){
                            var LT = sap.f && sap.f.LayoutType;
                            var one = (LT && LT.OneColumn) || 'OneColumn';
                            fcl.setLayout(one);
                            return 'set-one-column';
                          }
                          return 'no-fcl';
                        }catch(e){ return 'err:'+e; }
                        """
                    )
                except Exception:
                    mode = "err"
                wait_ui5_idle(self.driver, timeout=2)
                self._wait_not_busy(2)

        # Confirm we are back on list; fallback hard-navigate if not
        try:
            WebDriverWait(self.driver, 5).until(EC.element_to_be_clickable((By.XPATH, CREATE_BUTTON_XPATH)))
            return True
        except Exception:
            self.back_to_list()
            return True

    # -------- Footer Create clicks (staleness-safe; never closes dialog) --------
    def _click_footer_create(self, clicks: int = 1) -> dict:
        el = self._el()
        info = {"clicks": 0, "dialogs": [], "toasts": []}
        wait = WebDriverWait(self.driver, max(el._timeout, 25))

        def _find_footer_btn():
            try:
                return wait.until(EC.element_to_be_clickable((By.XPATH, ACTIVATE_CREATE_BTN_XPATH)))
            except TimeoutException:
                return wait.until(EC.element_to_be_clickable((By.XPATH, FORM_CREATE_OR_SAVE_BTN_XPATH)))

        for _ in range(max(1, clicks)):
            if self._dialog_open():
                info["dialogs"].append(self._capture_dialog_text() or "")
                break

            clicked_this_round = False
            for attempt in range(4):
                try:
                    btn = _find_footer_btn()
                    try:
                        self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
                    except Exception:
                        pass
                    try:
                        btn.click(); clicked_this_round = True; break
                    except ElementClickInterceptedException:
                        try:
                            btn2 = _find_footer_btn()
                            self.driver.execute_script("arguments[0].click();", btn2)
                            clicked_this_round = True; break
                        except StaleElementReferenceException:
                            continue
                    except StaleElementReferenceException:
                        continue
                except TimeoutException:
                    time.sleep(0.2); continue
                except Exception:
                    time.sleep(0.2); continue

            if not clicked_this_round:
                continue

            info["clicks"] += 1
            wait_ui5_idle(self.driver, timeout=max(el._timeout, 25))
            self._wait_not_busy(max(el._timeout, 25))

            try:
                txt = self.driver.execute_script(
                    "var nodes=document.querySelectorAll(arguments[0]);"
                    "if(!nodes||nodes.length===0) return '';"
                    "var t=nodes[nodes.length-1];"
                    "return (t.innerText||t.textContent||'').trim();",
                    MESSAGE_TOAST_CSS,
                )
                if isinstance(txt, str) and txt:
                    info["toasts"].append(txt)
            except Exception:
                pass
            time.sleep(0.25)

            if self._dialog_open():
                info["dialogs"].append(self._capture_dialog_text() or "")
                break

        return info

    # -------- Public: create + submit with verification --------
    def create_entry_and_submit(
        self,
        exch_type: str,
        from_ccy: str,
        to_ccy: str,
        valid_from_mmddyyyy: str,
        quotation: str,
        rate_str: str,
    ) -> dict:
        el = self._el()
        self.ensure_in_app()

        # 1) Open form
        self._click_list_create(timeout=el._timeout)
        self._screenshot("before_fill")

        # 2) Fill
        self._set_plain_input(EXCH_TYPE_INPUT_XPATH, exch_type)
        self._set_plain_input(FROM_CCY_INPUT_XPATH, from_ccy, press_enter=True)
        self._set_plain_input(TO_CCY_INPUT_XPATH, to_ccy, press_enter=True)
        self._set_plain_input(VALID_FROM_INPUT_XPATH, valid_from_mmddyyyy, press_enter=True)
        self._set_quotation_value(quotation)
        self._try_set_factor_by_label(FROM_FACTOR_BY_LABEL_XPATH, "1")
        self._try_set_factor_by_label(TO_FACTOR_BY_LABEL_XPATH, "1")

        self._set_rate_value_via_typing(rate_str)
        self._commit_rate_field(times=2)

        wait_ui5_idle(self.driver, timeout=el._timeout)
        self._wait_not_busy(el._timeout)

        # 3) Pre-submit validation
        err = self._has_validation_errors()
        if err and "greater than zero" in err.lower():
            self._try_set_factor_by_label(FROM_FACTOR_BY_LABEL_XPATH, "1")
            self._try_set_factor_by_label(TO_FACTOR_BY_LABEL_XPATH, "1")
            self._set_rate_value_ui5(rate_str)
            self._commit_rate_field(times=1)
            wait_ui5_idle(self.driver, timeout=el._timeout)
            self._wait_not_busy(el._timeout)
            err = self._has_validation_errors()

        if err:
            snap = self._screenshot("validation_error")
            return {
                "status": "validation_error",
                "error": err,
                "screenshot": snap,
                "dialog_open": self._dialog_open(),
                "dialog_text": self._capture_dialog_text() if self._dialog_open() else "",
            }

        # 4) Submit
        first_phase = self._click_footer_create(clicks=2)
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

        # 5) DONE gate: prefer header readiness, then close side column
        header_ready = self._wait_object_header_ready(timeout=min(10, max(8, el._timeout)))
        if header_ready:
            self._close_side_column_if_present(timeout=min(12, max(10, el._timeout)))
            snap = self._screenshot("after_create_closed")
            return {
                "status": "created",
                "footer_clicks": first_phase.get("clicks", 0),
                "intermediate_toasts": first_phase.get("toasts", []),
                "toast": "",
                "at_list": True,
                "dialog_open": False,
                "dialog_text": "",
                "screenshot": snap,
            }

        # Fallback (toast or already at list)
        final_phase = self._wait_for_success_toast_or_list(timeout=max(el._timeout, 18))
        if not final_phase.get("at_list"):
            # Even if no toast/list detected, force back to list to proceed
            self._close_side_column_if_present(timeout=min(12, max(10, el._timeout)))

        snap = self._screenshot("after_create")
        if final_phase.get("dialog"):
            return {
                "status": "dialog_open",
                "footer_clicks": first_phase.get("clicks", 0),
                "intermediate_toasts": first_phase.get("toasts", []),
                "toast": final_phase.get("toast", ""),
                "dialog_open": True,
                "dialog_text": final_phase.get("dialog", ""),
                "screenshot": snap,
            }

        # Final sanity check
        err2 = self._has_validation_errors()
        info = {
            "status": "created" if final_phase.get("at_list") or final_phase.get("toast") else "unknown",
            "footer_clicks": first_phase.get("clicks", 0),
            "intermediate_toasts": first_phase.get("toasts", []),
            "toast": final_phase.get("toast", ""),
            "at_list": True,   # we forced back to list if needed
            "dialog_open": False,
            "dialog_text": "",
            "screenshot": snap,
        }
        if err2:
            info["status"] = "validation_error"
            info["validation_after"] = err2
        return info

    # -------- Compatibility shim used by routes/currency.py --------
    def create_rate(
        self,
        exch_type: str,
        from_ccy: str,
        to_ccy: str,
        valid_from_mmddyyyy: str,
        quotation: str,
        rate_value: str | float,
    ) -> dict:
        return self.create_entry_and_submit(
            exch_type=exch_type,
            from_ccy=from_ccy,
            to_ccy=to_ccy,
            valid_from_mmddyyyy=valid_from_mmddyyyy,
            quotation=quotation,
            rate_str=str(rate_value),
        )
