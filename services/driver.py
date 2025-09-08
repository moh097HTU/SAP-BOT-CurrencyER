# services/driver.py
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from services.config import config

def get_driver(headless: bool = True) -> webdriver.Chrome:
    cfg = config()

    options = Options()
    if headless:
        options.add_argument("--headless=new")
    else:
        options.add_argument("--start-maximized")  # open full screen if not headless

    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-extensions")
    options.add_argument("--log-level=3")
    options.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
    options.add_experimental_option("useAutomationExtension", False)
    options.add_experimental_option("prefs", {
        "credentials_enable_service": False,
        "profile.password_manager_enabled": False
    })

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    driver.set_page_load_timeout(cfg["PAGELOAD_TIMEOUT_SECONDS"])

    # force maximize in case --start-maximized didn’t take effect
    if not headless:
        try:
            driver.maximize_window()
        except Exception:
            pass

    # reduce automation fingerprinting noise
    try:
        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {"source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"}
        )
    except Exception:
        pass

    return driver
