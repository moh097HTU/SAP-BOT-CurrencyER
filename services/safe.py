from selenium.webdriver.support.ui import WebDriverWait

def wait_js(driver, predicate_js: str, timeout: int) -> bool:
    try:
        WebDriverWait(driver, timeout).until(lambda d: bool(d.execute_script(predicate_js)))
        return True
    except Exception:
        return False
