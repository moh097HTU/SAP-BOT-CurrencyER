from core.base import Element
from .selectors import MESSAGE_TOAST_CSS

class ToastReader(Element):
    def read_last(self) -> str:
        try:
            txt = self.driver.execute_script(
                "var nodes=document.querySelectorAll(arguments[0]);"
                "if(!nodes||nodes.length===0) return '';"
                "var t=nodes[nodes.length-1];"
                "return (t.innerText||t.textContent||'').trim();",
                MESSAGE_TOAST_CSS,
            )
            return (txt or "").strip()
        except Exception:
            return ""
