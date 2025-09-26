# services/driver.py
from __future__ import annotations

import os
import threading
from pathlib import Path
import shutil
import stat
import time
import random
import gc

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.common.exceptions import SessionNotCreatedException, WebDriverException
from webdriver_manager.chrome import ChromeDriverManager

from services.config import config

_DRIVER_PATH_CACHE: str | None = None
_DRIVER_INIT_LOCK = threading.Lock()

_PROFILE_SET_LOCK = threading.Lock()
_PROFILE_DIRS_USED: set[str] = set()

def ensure_driver_binary_ready() -> str:
    global _DRIVER_PATH_CACHE
    if _DRIVER_PATH_CACHE:
        return _DRIVER_PATH_CACHE
    with _DRIVER_INIT_LOCK:
        if _DRIVER_PATH_CACHE:
            return _DRIVER_PATH_CACHE
        _DRIVER_PATH_CACHE = ChromeDriverManager().install()
        return _DRIVER_PATH_CACHE

def _base_profile_dir() -> Path:
    return Path(os.getenv("CHROME_USER_DATA_BASE", "chrome_profile")).resolve()

def _register_profile_dir(p: str) -> None:
    with _PROFILE_SET_LOCK:
        _PROFILE_DIRS_USED.add(p)

def list_profile_dirs_used() -> list[str]:
    with _PROFILE_SET_LOCK:
        return list(_PROFILE_DIRS_USED)

def _per_thread_profile_dir() -> str:
    base = _base_profile_dir()
    base.mkdir(parents=True, exist_ok=True)
    d = base / f"w-{threading.get_ident()}"
    d.mkdir(parents=True, exist_ok=True)
    p = str(d.resolve())
    _register_profile_dir(p)
    return p

def _random_debug_port() -> int:
    return random.randint(9223, 9550)

def get_driver(headless: bool = True) -> webdriver.Chrome:
    cfg = config()

    driver_path = ensure_driver_binary_ready()
    service = Service(driver_path)

    options = Options()
    if headless:
        options.add_argument("--headless=new")
    else:
        options.add_argument("--start-maximized")

    user_data_dir = _per_thread_profile_dir()
    options.add_argument(f"--user-data-dir={user_data_dir}")
    options.add_argument("--profile-directory=Default")

    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-features=Translate,BackForwardCache,Prerender2,VizDisplayCompositor")
    options.add_argument("--window-size=1366,768")
    options.add_argument("--lang=en-US")
    options.add_argument("--no-first-run")
    options.add_argument("--no-default-browser-check")

    options.add_argument("--log-level=3")
    options.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
    options.add_experimental_option("useAutomationExtension", False)
    options.add_experimental_option("prefs", {
        "credentials_enable_service": False,
        "profile.password_manager_enabled": False,
    })

    try:
        options.add_argument(f"--remote-debugging-port={_random_debug_port()}")
    except Exception:
        pass

    try:
        driver = webdriver.Chrome(service=service, options=options)
    except SessionNotCreatedException as e:
        raise RuntimeError(
            "Chrome/ChromeDriver version mismatch (SessionNotCreated). "
            "Install matching major versions of Chrome and Chromedriver. "
            f"Original: {e}"
        )
    except WebDriverException as e:
        raise RuntimeError(f"WebDriver failed to start: {type(e).__name__}: {e}")

    try:
        pl_timeout = int(cfg.get("PAGELOAD_TIMEOUT_SECONDS", 90)) or 90
        driver.set_page_load_timeout(pl_timeout)
    except Exception:
        try:
            driver.set_page_load_timeout(90)
        except Exception:
            pass

    if not headless:
        try:
            driver.maximize_window()
        except Exception:
            pass

    try:
        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {"source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"},
        )
    except Exception:
        pass

    try:
        setattr(driver, "_user_data_dir", user_data_dir)  # nosec
    except Exception:
        pass

    return driver

def _on_rm_error(func, path, exc_info):
    try:
        os.chmod(path, stat.S_IWRITE)
    except Exception:
        pass
    try:
        func(path)
    except Exception:
        pass

def _rmtree_force(p: Path, retries: int = 3, delay: float = 0.25):
    for _ in range(max(1, retries)):
        try:
            if p.exists():
                shutil.rmtree(p, onerror=_on_rm_error)
            return
        except Exception:
            time.sleep(delay)
    try:
        if p.exists():
            shutil.rmtree(p, onerror=_on_rm_error)
    except Exception:
        pass

def cleanup_profiles(also_base: bool = True) -> dict:
    deleted = []
    errors = []
    with _PROFILE_SET_LOCK:
        dirs = list(_PROFILE_DIRS_USED)
        _PROFILE_DIRS_USED.clear()
    for d in dirs:
        try:
            _rmtree_force(Path(d))
            deleted.append(d)
        except Exception as e:
            errors.append({"dir": d, "error": f"{type(e).__name__}: {e}"})
    base = _base_profile_dir()
    if also_base:
        try:
            if base.exists() and base.is_dir() and not any(base.iterdir()):
                _rmtree_force(base)
        except Exception:
            pass
    gc.collect()
    return {"deleted": deleted, "errors": errors}
