from core.base import Element
from .selectors import DIALOG_ROOT_CSS

class DialogWatcher(Element):
    def is_open(self) -> bool:
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

    def text(self) -> str:
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
