from selenium.webdriver.common.by import By
from core.base import Element
from .selectors import ANY_INVALID_INPUT_XPATH, ANY_ERROR_WRAPPER_XPATH

class ValidationInspector(Element):
    def collect(self) -> str | None:
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
