# services/driver.py
from __future__ import annotations
import os, threading, shutil, stat, time, random, gc, logging
from typing import Optional, List
from pathlib import Path
from shutil import which

from pyvirtualdisplay import Display
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.common.exceptions import SessionNotCreatedException, WebDriverException

from services.config import config

log = logging.getLogger("driver")
if not log.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    log.addHandler(h)
log.setLevel(logging.INFO)

# --- globals / env ---
_DRIVER_PATH_CACHE: str | None = None
_DRIVER_INIT_LOCK = threading.Lock()
_PROFILE_SET_LOCK = threading.Lock()
_PROFILE_DIRS_USED: set[str] = set()
_VDISPLAY_LOCK = threading.Lock()
_VDISPLAY: Display | None = None

CHROMEDRIVER_PATH_ENV = os.getenv("CHROMEDRIVER_PATH", "/usr/local/bin/chromedriver")
PAGELOAD_TIMEOUT_DEFAULT = int(os.getenv("PAGELOAD_TIMEOUT_SECONDS", "90") or "90")

# Force a virtual display in Docker so Chrome runs non-headless.
def _ensure_virtual_display() -> None:
    global _VDISPLAY
    if _VDISPLAY is not None:
        return
    with _VDISPLAY_LOCK:
        if _VDISPLAY is not None:
            return
        # 1920x1080x24 is safe; 'visible=0' means headless X server, but Chrome is in normal mode.
        _VDISPLAY = Display(visible=0, size=(1920, 1080), color_depth=24)
        _VDISPLAY.start()
        os.environ["DISPLAY"] = _VDISPLAY.new_display_var  # e.g., ":1001"
        log.info("Virtual X display started at %s", os.environ["DISPLAY"])

def _register_profile_dir(p: str) -> None:
    with _PROFILE_SET_LOCK:
        _PROFILE_DIRS_USED.add(p)

def list_profile_dirs_used() -> List[str]:
    with _PROFILE_SET_LOCK:
        return list(_PROFILE_DIRS_USED)

def _unique_profile_dir(base_dir: str = "/home/appuser/chrome-profiles") -> str:
    base = Path(base_dir); base.mkdir(parents=True, exist_ok=True)
    d = base / f"w-{os.getpid()}-{time.time_ns()}"
    d.mkdir(parents=True, exist_ok=True)
    os.chmod(d, 0o700)
    p = str(d.resolve()); _register_profile_dir(p); return p

def _strip_arg(options: Options, prefix: str) -> None:
    try:
        keep = [a for a in options.arguments if not a.startswith(prefix)]
        options._arguments = keep  # type: ignore[attr-defined]
    except Exception:
        pass

def ensure_driver_binary_ready() -> str:
    global _DRIVER_PATH_CACHE
    if _DRIVER_PATH_CACHE:
        return _DRIVER_PATH_CACHE
    with _DRIVER_INIT_LOCK:
        if _DRIVER_PATH_CACHE:
            return _DRIVER_PATH_CACHE
        path = which("chromedriver") or CHROMEDRIVER_PATH_ENV
        if not os.path.isfile(path):
            raise RuntimeError(f"chromedriver not found at '{path}'. Ensure Dockerfile baked it.")
        _DRIVER_PATH_CACHE = path
        return _DRIVER_PATH_CACHE

def _random_debug_port() -> int:
    return random.randint(9223, 9720)

def _base_options(download_dir: Optional[str]) -> Options:
    opts = Options()
    # NOTE: do NOT add --headless; we run non-headless under Xvfb
    opts.add_argument("--start-maximized")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-extensions")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--disable-features=Translate,BackForwardCache,Prerender2,VizDisplayCompositor")
    opts.add_argument("--window-size=1366,768")
    opts.add_argument("--lang=en-US")
    opts.add_argument("--no-first-run")
    opts.add_argument("--no-default-browser-check")
    opts.add_argument("--log-level=3")
    opts.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
    opts.add_experimental_option("useAutomationExtension", False)

    prefs = {
        "credentials_enable_service": False,
        "profile.password_manager_enabled": False,
    }
    if download_dir:
        dl = str(Path(download_dir).resolve()); Path(dl).mkdir(parents=True, exist_ok=True)
        prefs.update({
            "download.default_directory": dl,
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "safebrowsing.enabled": True,
            "savefile.default_directory": dl,
        })
    opts.add_experimental_option("prefs", prefs)

    try: opts.add_argument(f"--remote-debugging-port={_random_debug_port()}")
    except Exception: pass
    return opts

def _start_with(service: Service, options: Options, user_data_dir: Optional[str], timeout_s: int):
    _strip_arg(options, "--user-data-dir")
    _strip_arg(options, "--profile-directory")
    if user_data_dir:
        options.add_argument(f"--user-data-dir={user_data_dir}")
        options.add_argument(f"--profile-directory=Profile-{int(time.time()*1000)%1000000}")
    log.info("Launching Chrome (non-headless) | user_data_dir=%s | args=%s", user_data_dir, options.arguments)
    drv = webdriver.Chrome(service=service, options=options)
    drv.set_page_load_timeout(timeout_s)
    try:
        drv.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument",
            {"source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"})
    except Exception:
        pass
    return drv

def get_driver(headless: bool = False, download_dir: Optional[str] = None) -> webdriver.Chrome:
    """
    Non-headless in Docker via Xvfb.
    Fallbacks: unique profile -> new unique -> no user-data-dir.
    """
    # Always ensure our virtual display is up before launching Chrome.
    _ensure_virtual_display()

    svc = Service(ensure_driver_binary_ready())
    opts = _base_options(download_dir)
    timeout_s = PAGELOAD_TIMEOUT_DEFAULT

    p1 = _unique_profile_dir()
    try:
        return _start_with(svc, opts, p1, timeout_s)
    except SessionNotCreatedException as e:
        msg = str(e).lower()
        log.warning("Attempt#1 failed: %s", msg[:300])
        _cleanup_dir_silent(p1)
        if "user data directory is already in use" not in msg:
            raise _wrap_session_error(e)

    p2 = _unique_profile_dir()
    try:
        return _start_with(svc, opts, p2, timeout_s)
    except SessionNotCreatedException as e:
        msg = str(e).lower()
        log.warning("Attempt#2 failed: %s", msg[:300])
        _cleanup_dir_silent(p2)
        if "user data directory is already in use" not in msg:
            raise _wrap_session_error(e)

    log.warning("Attempt#3: starting WITHOUT user-data-dir (ephemeral tmp profile)")
    return _start_with(svc, opts, user_data_dir=None, timeout_s=timeout_s)

def _wrap_session_error(e: Exception) -> RuntimeError:
    return RuntimeError(
        "Failed to create Chrome session after fallbacks. "
        "Check chromedriver match, /dev/shm size, and conflicting args. "
        f"Original: {type(e).__name__}: {e}"
    )

def _on_rm_error(func, path, exc_info):
    try: os.chmod(path, stat.S_IWRITE)
    except Exception: pass
    try: func(path)
    except Exception: pass

def _rmtree_force(p: Path, retries: int = 3, delay: float = 0.25):
    for _ in range(max(1, retries)):
        try:
            if p.exists(): shutil.rmtree(p, onerror=_on_rm_error)
            return
        except Exception:
            time.sleep(delay)
    try:
        if p.exists(): shutil.rmtree(p, onerror=_on_rm_error)
    except Exception: pass

def _cleanup_dir_silent(path_str: str):
    try: _rmtree_force(Path(path_str))
    except Exception: pass

def cleanup_profiles(also_base: bool = True) -> dict:
    deleted, errors = [], []
    with _PROFILE_SET_LOCK:
        dirs = list(_PROFILE_DIRS_USED); _PROFILE_DIRS_USED.clear()
    for d in dirs:
        try: _rmtree_force(Path(d)); deleted.append(d)
        except Exception as e: errors.append({"dir": d, "error": f"{type(e).__name__}: {e}"})
    base = Path("/home/appuser/chrome-profiles")
    if also_base:
        try:
            if base.exists() and base.is_dir() and not any(base.iterdir()):
                _rmtree_force(base)
        except Exception: pass
    gc.collect()
    return {"deleted": deleted, "errors": errors}
