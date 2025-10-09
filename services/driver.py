# services/driver.py
from __future__ import annotations
import os, sys, threading, shutil, stat, time, random, gc, logging, platform
from typing import Optional, List, Tuple
from pathlib import Path
from shutil import which

# Make pyvirtualdisplay optional (Windows shouldn't require it)
try:
    from pyvirtualdisplay import Display  # type: ignore
except Exception:  # ImportError or runtime issues
    Display = None  # type: ignore

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.common.exceptions import SessionNotCreatedException, WebDriverException

from services.config import config  # if unused, keep to avoid breaking imports

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
_VDISPLAY: "Display | None" = None  # type: ignore

# OS / env detection
IS_WINDOWS = platform.system().lower().startswith("win")
IS_LINUX = platform.system().lower() == "linux"

def _is_docker() -> bool:
    """Detect Docker via /.dockerenv or cgroup hints."""
    if os.path.exists("/.dockerenv"):
        return True
    cgroup = "/proc/self/cgroup"
    try:
        if os.path.exists(cgroup):
            txt = Path(cgroup).read_text(errors="ignore")
            if "docker" in txt or "kubepods" in txt or "containerd" in txt:
                return True
    except Exception:
        pass
    return False

IN_DOCKER = _is_docker()

# Paths / timeouts
CHROMEDRIVER_PATH_ENV = os.getenv("CHROMEDRIVER_PATH", "/usr/local/bin/chromedriver")
PAGELOAD_TIMEOUT_DEFAULT = int(os.getenv("PAGELOAD_TIMEOUT_SECONDS", "90") or "90")

# Profile base dirs (overrideable)
LINUX_PROFILE_BASE_DEFAULT = "/home/appuser/chrome-profiles"
WINDOWS_PROFILE_BASE_DEFAULT = str(Path.cwd() / "chrome_profile")
CHROME_PROFILE_BASE = os.getenv(
    "CHROME_PROFILE_BASE",
    WINDOWS_PROFILE_BASE_DEFAULT if IS_WINDOWS else LINUX_PROFILE_BASE_DEFAULT,
)

def _ensure_virtual_display() -> None:
    """
    Start a virtual X display (Xvfb) when on Linux (bare metal or Docker).
    Windows must not call this.
    """
    global _VDISPLAY
    if _VDISPLAY is not None:
        return
    if not IS_LINUX:
        return

    with _VDISPLAY_LOCK:
        if _VDISPLAY is not None:
            return

        # If the host already provides DISPLAY, don't force Xvfb unless requested.
        force_xvfb = os.getenv("FORCE_XVFB", "1") != "0"
        if not force_xvfb and os.environ.get("DISPLAY"):
            log.info("DISPLAY is set; skipping virtual X display.")
            return

        if Display is None:
            msg = (
                "pyvirtualdisplay is not available but required for non-headless Chrome on Linux. "
                "Install it (and Xvfb) or set DISPLAY, or run headless."
            )
            log.warning(msg)
            return

        try:
            _VDISPLAY = Display(visible=0, size=(1920, 1080), color_depth=24)
            _VDISPLAY.start()
            os.environ["DISPLAY"] = getattr(_VDISPLAY, "new_display_var", os.environ.get("DISPLAY", ":99"))
            log.info("Virtual X display started at %s (docker=%s)", os.environ["DISPLAY"], IN_DOCKER)
        except Exception as e:
            log.warning("Failed to start virtual X display: %s", e)

def _register_profile_dir(p: str) -> None:
    with _PROFILE_SET_LOCK:
        _PROFILE_DIRS_USED.add(p)

def list_profile_dirs_used() -> List[str]:
    with _PROFILE_SET_LOCK:
        return list(_PROFILE_DIRS_USED)

def _unique_profile_dir(base_dir: Optional[str] = None) -> str:
    base_root = base_dir or CHROME_PROFILE_BASE
    base = Path(base_root)
    base.mkdir(parents=True, exist_ok=True)
    d = base / f"w-{os.getpid()}-{time.time_ns()}"
    d.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(d, 0o700)
    except Exception:
        pass
    p = str(d.resolve())
    _register_profile_dir(p)
    return p

def _strip_arg(options: Options, prefix: str) -> None:
    try:
        keep = [a for a in options.arguments if not a.startswith(prefix)]
        options._arguments = keep  # type: ignore[attr-defined]
    except Exception:
        pass

def _create_service() -> Service:
    """
    Windows: Prefer Selenium Manager when chromedriver isn't pinned.
    Linux/Docker: keep your pinned path by default, but fall back to Selenium Manager if missing.
    """
    explicit = CHROMEDRIVER_PATH_ENV if CHROMEDRIVER_PATH_ENV else None
    if explicit and os.path.isfile(explicit):
        return Service(executable_path=explicit)
    found = which("chromedriver")
    if found:
        return Service(executable_path=found)
    log.warning("chromedriver not found in env/PATH; using Selenium Manager to resolve ChromeDriver.")
    return Service()  # Selenium Manager

def _random_debug_port() -> int:
    return random.randint(9223, 9720)

# --- download helpers -------------------------------------------------

def _default_download_dir() -> Path:
    """Resolve a sane platform-specific Downloads directory."""
    # Allow env override first
    env = os.getenv("DOWNLOAD_DIR")
    if env:
        return Path(env).expanduser().resolve()
    home = Path.home()
    # Windows: %USERPROFILE%\Downloads ; Linux: ~/Downloads
    cand = home / "Downloads"
    try:
        cand.mkdir(parents=True, exist_ok=True)
    except Exception:
        # Fallback to cwd if we somehow cannot create Downloads
        cand = Path.cwd() / "downloads"
        cand.mkdir(parents=True, exist_ok=True)
    return cand.resolve()

def _chrome_prefs(download_dir: Path) -> dict:
    dl = str(download_dir)
    return {
        "download.default_directory": dl,
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "safebrowsing.enabled": True,
        # make PDFs download rather than open in tab (prevents hijacking)
        "plugins.always_open_pdf_externally": True,
        "download.open_pdf_in_system_reader": False,
        # allow multiple automatic downloads
        "profile.default_content_setting_values.automatic_downloads": 1,
        # some S4/HANA exports use blob URLs; this helps avoid nags
        "profile.default_content_setting_values.popups": 0,
        "credentials_enable_service": False,
        "profile.password_manager_enabled": False,
    }

def _base_options(download_dir: Optional[str]) -> Tuple[Options, Path]:
    opts = Options()

    # Window geometry: single, consistent value
    opts.add_argument("--window-size=1536,870")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-extensions")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--disable-features=Translate,BackForwardCache,Prerender2,VizDisplayCompositor")
    opts.add_argument("--lang=en-US")
    opts.add_argument("--no-first-run")
    opts.add_argument("--no-default-browser-check")
    opts.add_argument("--log-level=3")
    opts.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
    opts.add_experimental_option("useAutomationExtension", False)

    ua = os.getenv("CHROME_UA")
    if ua:
        opts.add_argument(f"user-agent={ua}")

    # Decide the download directory (always set one)
    dl_dir = Path(download_dir).expanduser().resolve() if download_dir else _default_download_dir()
    try:
        dl_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        log.warning("Failed to create download dir %s: %s; falling back to default", dl_dir, e)
        dl_dir = _default_download_dir()

    prefs = _chrome_prefs(dl_dir)
    opts.add_experimental_option("prefs", prefs)

    try:
        opts.add_argument(f"--remote-debugging-port={_random_debug_port()}")
    except Exception:
        pass

    # Respect HEADLESS if you later want it (still defaulting to non-headless)
    if os.getenv("HEADLESS", "0") == "1":
        # modern headless
        opts.add_argument("--headless=new")
    return opts, dl_dir

def _start_with(service: Service, options: Options, user_data_dir: Optional[str], timeout_s: int, download_dir: Path):
    _strip_arg(options, "--user-data-dir")
    _strip_arg(options, "--profile-directory")
    if user_data_dir:
        options.add_argument(f"--user-data-dir={user_data_dir}")
        options.add_argument(f"--profile-directory=Profile-{int(time.time()*1000)%1000000}")

    platform_tag = "windows" if IS_WINDOWS else ("linux-docker" if IN_DOCKER else "linux")
    log.info(
        "Launching Chrome (non-headless) | platform=%s | user_data_dir=%s | args=%s | downloads=%s",
        platform_tag, user_data_dir, options.arguments, download_dir
    )

    drv = webdriver.Chrome(service=service, options=options)
    drv.set_page_load_timeout(timeout_s)

    # CDP: allow downloads explicitly (helps with some blob-based flows)
    try:
        drv.execute_cdp_cmd("Page.setDownloadBehavior", {
            "behavior": "allow",
            "downloadPath": str(download_dir)
        })
    except Exception:
        pass

    try:
        # Anti-detection: remove webdriver flag
        drv.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {"source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"}
        )
    except Exception:
        pass
    return drv

def ensure_driver_binary_ready() -> str:
    """
    Kept for backward compatibility. On Windows, you likely rely on Selenium Manager;
    on Linux/Docker we honor pinned path when present.
    """
    global _DRIVER_PATH_CACHE
    if _DRIVER_PATH_CACHE:
        return _DRIVER_PATH_CACHE
    with _DRIVER_INIT_LOCK:
        if _DRIVER_PATH_CACHE:
            return _DRIVER_PATH_CACHE

        path = which("chromedriver")
        if not path:
            path = CHROMEDRIVER_PATH_ENV

        if path and os.path.isfile(path):
            _DRIVER_PATH_CACHE = path
            return _DRIVER_PATH_CACHE

        if IS_WINDOWS:
            log.warning("chromedriver not found; Windows will use Selenium Manager dynamically.")
            _DRIVER_PATH_CACHE = ""
            return _DRIVER_PATH_CACHE

        raise RuntimeError(
            f"chromedriver not found at '{path}'. Ensure Dockerfile baked it or allow Selenium Manager."
        )

def get_driver(headless: bool = False, download_dir: Optional[str] = None) -> webdriver.Chrome:
    """
    Cross-platform launcher:
      - Linux (bare metal or Docker): non-headless via Xvfb (if available).
      - Windows: non-headless directly.
    """
    if IS_LINUX:
        _ensure_virtual_display()

    svc = _create_service()
    opts, dl_dir = _base_options(download_dir)
    timeout_s = PAGELOAD_TIMEOUT_DEFAULT

    # Try with unique profile dir 1
    p1 = _unique_profile_dir()
    try:
        return _start_with(svc, opts, p1, timeout_s, dl_dir)
    except SessionNotCreatedException as e:
        msg = str(e).lower()
        log.warning("Attempt#1 failed: %s", msg[:300])
        _cleanup_dir_silent(p1)
        if "user data directory is already in use" not in msg:
            raise _wrap_session_error(e)
    except WebDriverException as e:
        if IS_LINUX and "chrome not reachable" in str(e).lower():
            log.warning("Chrome not reachable — verify Xvfb/DISPLAY and /dev/shm size.")
        _cleanup_dir_silent(p1)
        raise

    # Try with unique profile dir 2
    p2 = _unique_profile_dir()
    try:
        return _start_with(svc, opts, p2, timeout_s, dl_dir)
    except SessionNotCreatedException as e:
        msg = str(e).lower()
        log.warning("Attempt#2 failed: %s", msg[:300])
        _cleanup_dir_silent(p2)
        if "user data directory is already in use" not in msg:
            raise _wrap_session_error(e)

    # Last attempt: no user-data-dir (ephemeral)
    log.warning("Attempt#3: starting WITHOUT user-data-dir (ephemeral tmp profile)")
    return _start_with(svc, opts, user_data_dir=None, timeout_s=timeout_s, download_dir=dl_dir)

def _wrap_session_error(e: Exception) -> RuntimeError:
    return RuntimeError(
        "Failed to create Chrome session after fallbacks. "
        "Check chromedriver match, /dev/shm size, virtual display (Linux), and conflicting args. "
        f"Original: {type(e).__name__}: {e}"
    )

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

def _cleanup_dir_silent(path_str: str):
    try:
        _rmtree_force(Path(path_str))
    except Exception:
        pass

def cleanup_profiles(also_base: bool = True) -> dict:
    deleted, errors = [], []
    with _PROFILE_SET_LOCK:
        dirs = list(_PROFILE_DIRS_USED)
        _PROFILE_DIRS_USED.clear()
    for d in dirs:
        try:
            _rmtree_force(Path(d))
            deleted.append(d)
        except Exception as e:
            errors.append({"dir": d, "error": f"{type(e).__name__}: {e}"})

    base = Path(CHROME_PROFILE_BASE)
    if also_base:
        try:
            if base.exists() and base.is_dir() and not any(base.iterdir()):
                _rmtree_force(base)
        except Exception:
            pass

    gc.collect()
    return {"deleted": deleted, "errors": errors}

# --- optional: exact viewport helper ----------------------------------

def set_exact_viewport(driver: webdriver.Chrome, vw: int, vh: int) -> None:
    """Resize outer window so that viewport equals (vw, vh)."""
    try:
        inner_w, inner_h = driver.execute_script("return [window.innerWidth, window.innerHeight];")
        outer = driver.get_window_size()
        chrome_w = outer["width"] - inner_w
        chrome_h = outer["height"] - inner_h
        driver.set_window_size(vw + chrome_w, vh + chrome_h)
    except Exception as e:
        log.debug("set_exact_viewport failed: %s", e)
