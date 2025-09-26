from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from selenium.common.exceptions import TimeoutException, StaleElementReferenceException
import time

from core.base import Element
from services.ui import wait_ui5_idle
from ..ListToolbar.element import ListToolbar
from .selectors import CLOSE_COLUMN_BTN_XPATH

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

class SideColumnController(Element):
    def close_if_present(self, timeout: int | None = None) -> bool:
        t = timeout or max(self._timeout, 20)
        listbar = ListToolbar(self.driver)

        if listbar.is_at_list(quick=0.8):
            return True

        try:
            btn = WebDriverWait(self.driver, min(5, t), ignored_exceptions=(StaleElementReferenceException,)).until(
                EC.element_to_be_clickable((By.XPATH, CLOSE_COLUMN_BTN_XPATH))
            )
            try:
                self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
            except Exception:
                pass
            try:
                _retry_stale(lambda: btn.click())
            except Exception:
                self.js_click(btn)
            wait_ui5_idle(self.driver, timeout=min(6, t))
        except TimeoutException:
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

            if did != "clicked-dom":
                try:
                    _ = self.driver.execute_script(
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
                    _ = "err"
                wait_ui5_idle(self.driver, timeout=2)

        if listbar.is_at_list(quick=1.0):
            return True
        return True
