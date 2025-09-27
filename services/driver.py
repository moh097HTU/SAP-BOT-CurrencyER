# services/driver.py
# -----------------------------------------------
# FULL FILE (adds download_dir support & unified prefs)
# -----------------------------------------------
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
    with _DRIVER_PATH_CACHE_LOCK():
        if _DRIVER_PATH_CACHE:
            return _DRIVER_PATH_CACHE
        _DRIVER_PATH_CACHE = ChromeDriverManager().install()
        return _DRIVER_PATH_CACHE

def _DRIVER_PATH_CACHE_LOCK():
    # backward-compatible simple lock factory (kept separate in case of future refactors)
    return _DRIVER_INIT_LOCK

def _base_profile_dir() -> Path:
    return Path(os.getenv("CHROME_USER_DATA_BASE", "chrome_profile")).resolve()

def _register_profile_dir(p: str) -> None:
    with _PROFILE_SET_LOCK:
        _PROFILE_DIRS_USED.add(p)

def list_profile_dirs_used() -> list[str]:
    with _PROFILE_SET_LOCK:
        return list(_PROFILE_DIRS_USED)

def _per_thread_profile_dir() -> str:
    """
    Use a process-unique + thread-unique Chrome user-data directory to avoid
    cross-process collisions on profile locks. Format: w-<pid>-<thread_id>
    """
    base = _base_profile_dir()
    base.mkdir(parents=True, exist_ok=True)
    pid = os.getpid()
    tid = threading.get_ident()
    d = base / f"w-{pid}-{tid}"
    d.mkdir(parents=True, exist_ok=True)
    p = str(d.resolve())
    _register_profile_dir(p)
    return p

def _random_debug_port() -> int:
    return random.randint(9223, 9550)

def get_driver(headless: bool = True, download_dir: str | None = None) -> webdriver.Chrome:
    """
    Create a Chrome driver. If download_dir is provided, Chrome will save files there silently.
    """
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

    # -------- unified prefs (includes optional download_dir) --------
    prefs = {
        "credentials_enable_service": False,
        "profile.password_manager_enabled": False,
    }
    if download_dir:
        dl = str(Path(download_dir).resolve())
        Path(dl).mkdir(parents=True, exist_ok=True)
        prefs.update({
            "download.default_directory": dl,
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "safebrowsing.enabled": True,
            "savefile.default_directory": dl,
        })
    options.add_experimental_option("prefs", prefs)
    # ---------------------------------------------------------------

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

    # Hide webdriver flag (minor hardening)
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

# ---------- OS-level cleanup (best-effort) ----------

def _safe_str(s) -> str:
    try:
        return str(s or "")
    except Exception:
        return ""

def _cmdline_has_userdata_under_base(cmdline: list[str], base: Path) -> bool:
    b = str(base)
    for arg in cmdline or []:
        a = _safe_str(arg)
        if "--user-data-dir=" in a:
            try:
                path = a.split("=", 1)[1]
            except Exception:
                path = ""
            if path and Path(path).resolve().as_posix().startswith(base.as_posix()):
                return True
    for i, a in enumerate(cmdline or []):
        if a == "--user-data-dir" and i + 1 < len(cmdline):
            path = _safe_str(cmdline[i + 1])
            if path and Path(path).resolve().as_posix().startswith(base.as_posix()):
                return True
        if b in _safe_str(a):
            return True
    return False

def _should_kill(proc, base: Path) -> bool:
    try:
        name = _safe_str(proc.info.get("name")).lower()
        cmd  = proc.info.get("cmdline") or []
    except Exception:
        return False

    chrome_names = {"chrome", "chrome.exe", "google-chrome", "chromium", "chromium-browser"}
    driver_names = {"chromedriver", "chromedriver.exe"}

    if name in chrome_names and _cmdline_has_userdata_under_base(cmd, base):
        return True

    if name in driver_names:
        if _cmdline_has_userdata_under_base(cmd, base):
            return True
        try:
            for child in proc.children(recursive=True):
                try:
                    from psutil import NoSuchProcess  # type: ignore
                    cname = _safe_str(child.name()).lower()
                    ccmd  = child.cmdline() or []
                    if cname in chrome_names and _cmdline_has_userdata_under_base(ccmd, base):
                        return True
                except Exception:
                    continue
        except Exception:
            pass
    return False

def kill_strays() -> dict:
    try:
        import psutil  # type: ignore
    except Exception:
        return {"ok": False, "reason": "psutil_missing"}

    base = _base_profile_dir()
    killed: list[int] = []
    errs: list[dict] = []

    try:
        for proc in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                if _should_kill(proc, base):
                    try:
                        proc.terminate()
                    except Exception:
                        pass
                    try:
                        proc.wait(timeout=1.5)
                    except Exception:
                        try:
                            proc.kill()
                        except Exception as e:
                            errs.append({"pid": proc.pid, "err": f"kill_failed:{type(e).__name__}"})
                            continue
                    killed.append(proc.pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
            except Exception as e:
                errs.append({"pid": getattr(proc, "pid", -1), "err": f"{type(e).__name__}"})
                continue
    except Exception as e:
        return {"ok": False, "reason": f"iter_failed:{type(e).__name__}"}

    return {"ok": True, "killed": killed, "errors": errs}

# ---------- filesystem cleanup ----------

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
    try:
        _ = kill_strays()
    except Exception:
        pass

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
