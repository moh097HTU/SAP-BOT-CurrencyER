from decimal import Decimal, ROUND_HALF_UP
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.common.action_chains import ActionChains
from core.base import Element
from services.ui import wait_ui5_idle
from .selectors import EXCH_RATE_INPUT_XPATH, EXCH_RATE_INPUT_FALLBACK_XPATH

class ExchangeRateField(Element):
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

    def _find_input(self):
        try:
            return self.wait_visible(By.XPATH, EXCH_RATE_INPUT_XPATH)
        except Exception:
            pass
        try:
            return self.wait_visible(By.XPATH, EXCH_RATE_INPUT_FALLBACK_XPATH)
        except Exception:
            raise RuntimeError("Exchange Rate input not found (primary nor fallback).")

    def _hard_clear(self, el):
        for js in (
            lambda: el.clear(),
            lambda: el.send_keys(Keys.CONTROL, "a"),
            lambda: el.send_keys(Keys.DELETE),
            lambda: self.driver.execute_script(
                "arguments[0].value='';"
                "arguments[0].dispatchEvent(new Event('input',{bubbles:true}));"
                "arguments[0].dispatchEvent(new Event('change',{bubbles:true}));", el),
        ):
            try: js()
            except Exception: pass

    def commit(self, times: int = 1):
        inp = self._find_input()
        try:
            self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", inp)
        except Exception:
            pass
        try:
            inp.click()
        except Exception:
            self.js_click(inp)

        try:
            ac = ActionChains(self.driver)
            for _ in range(max(1, times)):
                ac.send_keys(Keys.ENTER).pause(0.03)
            ac.send_keys(Keys.TAB)
            ac.perform()
        except Exception:
            try:
                inp.send_keys(Keys.ENTER); inp.send_keys(Keys.TAB)
            except Exception: pass

        # trimmed post-commit idle wait
        wait_ui5_idle(self.driver, timeout=min(self._timeout, 4))

    def set_via_typing(self, rate_val: str | float | Decimal):
        num = Decimal(str(rate_val))
        if num <= 0:
            raise ValueError("rate_val must be > 0")
        s = self._format_rate_locale(num)
        inp = self._find_input()
        self._hard_clear(inp)
        inp.send_keys(s)
        try: inp.send_keys(Keys.TAB)
        except Exception: pass
        wait_ui5_idle(self.driver, timeout=min(self._timeout, 4))

    def set_via_ui5(self, rate_val: str | float | Decimal):
        inp = self._find_input()
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
        wait_ui5_idle(self.driver, timeout=min(self._timeout, 4))
        if not res or not res.get("ok"):
            raise RuntimeError(f"Could not set Exchange Rate via UI5. Result={res}.")
