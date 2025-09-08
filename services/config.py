# services/config.py
from dotenv import load_dotenv
import os

load_dotenv()

_BOOL = {"1", "true", "yes", "on", "y", "t"}

def _as_bool(v: str, default=False) -> bool:
    if v is None:
        return default
    return v.strip().lower() in _BOOL

def _as_int(v: str, default: int) -> int:
    try:
        return int(v)
    except Exception:
        return default

def config():
    sap_url = os.getenv("SAP_URL", "https://my413369.s4hana.cloud.sap/ui#Shell-home")
    return {
        "SAP_URL": sap_url,
        "ROOT_URL": sap_url,  # alias to avoid KeyErrors in callers
        "SAP_USERNAME": os.getenv("SAP_USERNAME", ""),
        "SAP_PASSWORD": os.getenv("SAP_PASSWORD", ""),

        "HEADLESS": _as_bool(os.getenv("HEADLESS", "false")),
        "EXPLICIT_WAIT_SECONDS": _as_int(os.getenv("EXPLICIT_WAIT_SECONDS", "30"), 30),
        "PAGELOAD_TIMEOUT_SECONDS": _as_int(os.getenv("PAGELOAD_TIMEOUT_SECONDS", "90"), 90),
        "KEEP_BROWSER": _as_bool(os.getenv("KEEP_BROWSER", "true")),
        "SCREENSHOT_PATH": os.getenv("SCREENSHOT_PATH", "after_click.png"),
    }

# Legacy convenience
ROOT_URL = config()["ROOT_URL"]
EXPLICIT_WAIT_SEC = config()["EXPLICIT_WAIT_SECONDS"]
