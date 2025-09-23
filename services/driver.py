# services/driver.py
from __future__ import annotations

import os
import threading
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

from services.config import config

# Cache the chromedriver path once to avoid Windows file-lock races
_DRIVER_PATH_CACHE: str | None = None
_DRIVER_INIT_LOCK = threading.Lock()


def ensure_driver_binary_ready() -> str:
    """
    Download/resolve chromedriver exactly once per process.
    Prevents PermissionError: [WinError 32] when many threads try to install at once.
    """
    global _DRIVER_PATH_CACHE
    if _DRIVER_PATH_CACHE:
        return _DRIVER_PATH_CACHE
    with _DRIVER_INIT_LOCK:
        if _DRIVER_PATH_CACHE:
            return _DRIVER_PATH_CACHE
        _DRIVER_PATH_CACHE = ChromeDriverManager().install()
        return _DRIVER_PATH_CACHE


def _per_thread_profile_dir() -> str:
    """
    Unique user-data-dir per worker thread → hard isolation of Chrome sessions.
    Example: chrome_profile/w-140691297104304
    You can override base via CHROME_USER_DATA_BASE env var.
    """
    base = Path(os.getenv("CHROME_USER_DATA_BASE", "chrome_profile"))
    # Ensure base exists
    base.mkdir(parents=True, exist_ok=True)
    # Thread-ident is unique enough for our worker model
    d = base / f"w-{threading.get_ident()}"
    d.mkdir(parents=True, exist_ok=True)
    return str(d.resolve())


def get_driver(headless: bool = True) -> webdriver.Chrome:
    cfg = config()

    # Make sure the driver binary is ready before we build the Service (prevents WinError 32)
    driver_path = ensure_driver_binary_ready()
    service = Service(driver_path)

    options = Options()
    if headless:
        # new headless is more stable with UI5 than legacy
        options.add_argument("--headless=new")
    else:
        options.add_argument("--start-maximized")

    # Per-thread profile isolation (the fix for “some windows just sit there”)
    user_data_dir = _per_thread_profile_dir()
    options.add_argument(f"--user-data-dir={user_data_dir}")
    # Keep a deterministic profile inside that dir (Chrome expects one)
    options.add_argument("--profile-directory=Default")

    # Typical stability flags
    #options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-extensions")
    options.add_argument("--log-level=3")
    options.add_argument("--disable-features=Translate,BackForwardCache,Prerender2")
    options.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
    options.add_experimental_option("useAutomationExtension", False)
    options.add_experimental_option(
        "prefs",
        {
            "credentials_enable_service": False,
            "profile.password_manager_enabled": False,
        },
    )

    driver = webdriver.Chrome(service=service, options=options)
    driver.set_page_load_timeout(cfg["PAGELOAD_TIMEOUT_SECONDS"])

    if not headless:
        try:
            driver.maximize_window()
        except Exception:
            pass

    # Reduce automation fingerprinting noise
    try:
        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {"source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"},
        )
    except Exception:
        pass

    return driver
