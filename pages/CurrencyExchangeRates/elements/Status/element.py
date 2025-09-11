# elements/Status/element.py
import time
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By

from core.base import Element
from .selectors import (
    HEADER_EDIT_BTN_XPATH, HEADER_DELETE_BTN_XPATH, HEADER_COPY_BTN_XPATH,
    FOOTER_DISCARD_DRAFT_BTN_XPATH,
    CHANGE_LOG_SECTION_ANCHOR_XPATH, TREND_SECTION_ANCHOR_XPATH,
    OBJECT_HEADER_CONTENT_XPATH,
)

class StatusProbe(Element):
    """Reads robust 'done' signals:
       - IsActiveEntity from bound context (server truth)
       - Buttons flip (Edit/Delete/Copy appear, Discard Draft disappears)
       - Sections appear (Change Log / Trend)
       - Header aria-label turns concrete (not 'New …')
    """

    def _exists(self, xp: str, t: float = 0.7) -> bool:
        try:
            WebDriverWait(self.driver, t).until(EC.presence_of_element_located((By.XPATH, xp)))
            return True
        except Exception:
            return False

    def is_active_entity(self):
        """True/False if found, or None when not determinable."""
        try:
            res = self.driver.execute_script(
                """
                try{
                  var core=sap && sap.ui && sap.ui.getCore && sap.ui.getCore();
                  if(!core) return {ok:false, why:'no-core'};
                  var els = core && core.mElements ? Object.values(core.mElements) : [];
                  // Prefer ObjectPageLayout
                  for (var i=0;i<els.length;i++){
                    var c=els[i];
                    try{
                      var n=c.getMetadata&&c.getMetadata().getName&&c.getMetadata().getName();
                      if(n==='sap.uxap.ObjectPageLayout'){
                        var bc=c.getBindingContext&&c.getBindingContext();
                        if(bc){
                          var o=bc.getObject&&bc.getObject();
                          if(o && ('IsActiveEntity' in o)) return {ok:true, active: !!o.IsActiveEntity};
                          var p=bc.getProperty&&bc.getProperty('IsActiveEntity');
                          if(typeof p!=='undefined') return {ok:true, active: !!p};
                        }
                      }
                    }catch(e){}
                  }
                  // Fallback: any control with IsActiveEntity
                  for (var j=0;j<els.length;j++){
                    var c2=els[j];
                    try{
                      var bc2=c2.getBindingContext&&c2.getBindingContext();
                      if(bc2){
                        var p2=bc2.getProperty&&bc2.getProperty('IsActiveEntity');
                        if(typeof p2!=='undefined') return {ok:true, active: !!p2};
                      }
                    }catch(e){}
                  }
                  return {ok:false, why:'no-binding'};
                }catch(e){ return {ok:false, why:String(e)}; }
                """
            )
            if isinstance(res, dict) and res.get("ok"):
                return bool(res.get("active"))
        except Exception:
            pass
        return None

    def buttons_state(self) -> dict:
        return {
            "has_edit":   self._exists(HEADER_EDIT_BTN_XPATH),
            "has_delete": self._exists(HEADER_DELETE_BTN_XPATH),
            "has_copy":   self._exists(HEADER_COPY_BTN_XPATH),
            "has_discard_draft": self._exists(FOOTER_DISCARD_DRAFT_BTN_XPATH),
        }

    def sections_present(self) -> dict:
        return {
            "has_log":   self._exists(CHANGE_LOG_SECTION_ANCHOR_XPATH),
            "has_trend": self._exists(TREND_SECTION_ANCHOR_XPATH),
        }

    def header_aria_label(self) -> str:
        try:
            el = WebDriverWait(self.driver, 0.7).until(
                EC.presence_of_element_located((By.XPATH, OBJECT_HEADER_CONTENT_XPATH))
            )
            return (el.get_attribute("aria-label") or "").strip()
        except Exception:
            return ""

    def success(self) -> bool:
        """Combine all cues into a robust success predicate."""
        active = self.is_active_entity()
        if active is True:
            return True

        btns = self.buttons_state()
        if btns["has_edit"] and not btns["has_discard_draft"]:
            return True

        secs = self.sections_present()
        if secs["has_log"] or secs["has_trend"]:
            return True

        aria = self.header_aria_label()
        if aria and "Header area" in aria and "New" not in aria:
            return True

        return False
