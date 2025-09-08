# services/ui.py
from selenium.webdriver.support.ui import WebDriverWait
from services.config import EXPLICIT_WAIT_SEC

def _wait_js(driver, script: str, timeout: int) -> bool:
    try:
        WebDriverWait(driver, timeout).until(lambda d: bool(d.execute_script(script)))
        return True
    except Exception:
        return False

def wait_for_shell_home(driver, timeout: int | None = None) -> bool:
    """
    Ready when:
      - URL contains '#Shell-home', OR
      - UI5 core is initialized and ushell container is present.
    """
    t = timeout or EXPLICIT_WAIT_SEC
    try:
        WebDriverWait(driver, t).until(
            lambda d: "shell-home" in (d.current_url or "").lower()
        )
        return True
    except Exception:
        pass

    js = """
    try {
      if (!window.sap || !sap.ui) return false;
      if (sap.ushell && sap.ushell.Container) return true;
      var core = sap.ui.getCore && sap.ui.getCore();
      if (!core) return false;
      if (core.isInitialized && !core.isInitialized()) return false;
      return true;
    } catch (e) { return false; }
    """
    return _wait_js(driver, js, t)

def wait_ui5_idle(driver, timeout: int | None = None) -> bool:
    """
    Lightweight 'settled' check for UI5 renderer and DOM idle enough to interact.
    """
    t = timeout or EXPLICIT_WAIT_SEC
    js = """
    try {
      if (document.readyState !== 'complete') return false;
      if (window.sap && sap.ui && sap.ui.getCore) {
        var core = sap.ui.getCore();
        if (core && core.isInitialized && !core.isInitialized()) return false;
        if (core && core.getUIDirty && core.getUIDirty()) return false;
      }
      return true;
    } catch (e) { return true; }
    """
    return _wait_js(driver, js, t)

def wait_url_contains(driver, needle: str, timeout: int | None = None) -> bool:
    t = timeout or EXPLICIT_WAIT_SEC
    try:
        WebDriverWait(driver, t).until(
            lambda d: needle.lower() in (d.current_url or "").lower()
        )
        return True
    except Exception:
        return False

# ---------- NEW: robust shell search readiness + JS fallback ----------

def wait_shell_search_ready(driver, timeout: int | None = None) -> bool:
    """
    Wait until the FLP header search control is available OR the renderer exists.
    """
    t = timeout or EXPLICIT_WAIT_SEC
    js = """
    try {
      var hasSearch = !!document.querySelector('a#sf.sapUshellShellHeadItm')
                   || !!document.querySelector("a.sapUshellShellHeadItm[data-help-id='shellHeader-search']")
                   || !!document.querySelector("a.sapUshellShellHeadItm[role='button'][aria-label*='Search']");
      if (hasSearch) return true;
      if (window.sap && sap.ushell && sap.ushell.Container) {
         var r = sap.ushell.Container.getRenderer && sap.ushell.Container.getRenderer();
         if (r) return true;
      }
      return false;
    } catch(e){ return false; }
    """
    return _wait_js(driver, js, t)

def open_shell_search_via_js(driver) -> bool:
    """
    Ask the FLP renderer to open the global search.
    Returns True if we could call an API; False otherwise.
    """
    js = """
    try {
      if (window.sap && sap.ushell && sap.ushell.Container){
         var r = sap.ushell.Container.getRenderer && sap.ushell.Container.getRenderer();
         if (r){
            if (typeof r.showSearch === 'function'){ r.showSearch(true); return true; }
            if (typeof r.openSearch === 'function'){ r.openSearch(); return true; }
         }
      }
    } catch(e){}
    return false;
    """
    try:
        return bool(driver.execute_script(js))
    except Exception:
        return False
