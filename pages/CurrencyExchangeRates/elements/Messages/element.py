from core.base import Element

class Ui5Messages(Element):
    """
    Reads UI5 MessageManager; surfaces backend errors (why activation fails).
    Also knows how to read the Message Popover DOM (title/subtitle/description)
    which is what your HTML snippet shows.
    """

    def _get_data(self):
        try:
            return self.driver.execute_script(
                """
                try{
                  var core = sap && sap.ui && sap.ui.getCore ? sap.ui.getCore() : null;
                  if(!core) return {ok:false, data:[]};
                  var mm = core.getMessageManager && core.getMessageManager();
                  if(!mm) return {ok:false, data:[]};
                  var model = mm.getMessageModel && mm.getMessageModel();
                  if(!model) return {ok:false, data:[]};
                  var data = (model.getData && model.getData()) || model.oData || [];
                  var out = [];
                  for (var i=0;i<data.length;i++){
                    var m=data[i]||{};
                    out.push({
                      type: String(m.type||''),
                      message: String(m.message||m.text||'').trim(),
                      description: String(m.description||'').trim(),
                      code: String(m.code||'').trim(),
                      target: String(m.target||'').trim(),
                      technical: !!m.technical
                    });
                  }
                  return {ok:true, data:out};
                }catch(e){ return {ok:false, data:[], err:String(e)}; }
                """
            ) or {"ok": False, "data": []}
        except Exception:
            return {"ok": False, "data": []}

    def read_all(self):
        res = self._get_data()
        return res.get("data", []) if isinstance(res, dict) else []

    def errors(self):
        return [m for m in self.read_all() if (m.get("type") or "").lower() in ("error","fatal","critical")]

    def has_errors(self) -> bool:
        return len(self.errors()) > 0

    def clear(self) -> bool:
        try:
            return bool(self.driver.execute_script(
                """
                try{
                  var core = sap && sap.ui && sap.ui.getCore ? sap.ui.getCore() : null;
                  var mm = core && core.getMessageManager && core.getMessageManager();
                  if(!mm) return false;
                  if(mm.removeAllMessages) { mm.removeAllMessages(); return true; }
                  return false;
                }catch(e){ return false; }
                """
            ))
        except Exception:
            return False

    # ---------- NEW: Message Popover DOM reader ----------

    def popover_text(self) -> str:
        try:
            txt = self.driver.execute_script(
                """
                try{
                  function visible(el){
                    if(!el) return false;
                    var cs = getComputedStyle(el);
                    if(cs.display==='none'||cs.visibility==='hidden') return false;
                    var r = el.getBoundingClientRect();
                    return r.width>0 && r.height>0;
                  }

                  var wrap = document.querySelector('.sapMPopoverWrapper');
                  if(!wrap || !visible(wrap)) return '';

                  var errIcon = wrap.querySelector('.sapMMsgViewDescIconError');
                  var errStrip = document.querySelector('.sapMMsgStrip.sapMMsgStripError');
                  var isErr = !!(errIcon || errStrip);

                  var titleEl = wrap.querySelector('.sapMMsgView .sapMMsgViewTitleText .sapMLnkText');
                  var subEl   = wrap.querySelector('.sapMMsgView .sapMMsgViewSubtitleText');
                  var descEl  = wrap.querySelector('.sapMMsgView .sapMMsgViewDescriptionText');

                  var title = titleEl ? (titleEl.innerText||titleEl.textContent||'').trim() : '';
                  var sub   = subEl   ? (subEl.innerText||subEl.textContent||'').trim() : '';
                  var desc  = descEl  ? (descEl.innerText||descEl.textContent||'').trim() : '';

                  if(!isErr && !title && !desc) return '';
                  var parts = [];
                  if(title) parts.push(title);
                  if(sub)   parts.push(sub);
                  if(desc)  parts.push(desc);
                  return parts.join(' | ');
                }catch(e){ return ''; }
            """
            )
            return (txt or "").strip()
        except Exception:
            return ""
