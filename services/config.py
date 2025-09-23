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
        # SAP / browser
        "SAP_URL": sap_url,
        "ROOT_URL": sap_url,  # alias to avoid KeyErrors in callers
        "SAP_USERNAME": os.getenv("SAP_USERNAME", ""),
        "SAP_PASSWORD": os.getenv("SAP_PASSWORD", ""),

        "HEADLESS": _as_bool(os.getenv("HEADLESS", "false")),
        "EXPLICIT_WAIT_SECONDS": _as_int(os.getenv("EXPLICIT_WAIT_SECONDS", "30"), 30),
        "PAGELOAD_TIMEOUT_SECONDS": _as_int(os.getenv("PAGELOAD_TIMEOUT_SECONDS", "90"), 90),
        "KEEP_BROWSER": _as_bool(os.getenv("KEEP_BROWSER", "true")),

        # Multithreading
        "NUM_WORKERS": _as_int(os.getenv("NUM_WORKERS", "4"), 4),
        "LOGIN_CONCURRENCY": _as_int(os.getenv("LOGIN_CONCURRENCY", "2"), 2),
        "WATCHDOG_SECONDS": _as_int(os.getenv("WATCHDOG_SECONDS", "200"), 200),
        "CHROME_USER_DATA_BASE": os.getenv("CHROME_USER_DATA_BASE", "chrome_profile"),

        # Reporting
        "REPORTS_DIR": os.getenv("REPORTS_DIR", "reports"),

        # Email (Outlook via Microsoft Graph)
        "EMAIL_ENABLED": _as_bool(os.getenv("EMAIL_ENABLED", "false")),
        "OUTLOOK_TENANT_ID": os.getenv("OUTLOOK_TENANT_ID", ""),
        "OUTLOOK_CLIENT_ID": os.getenv("OUTLOOK_CLIENT_ID", ""),
        "OUTLOOK_CLIENT_SECRET": os.getenv("OUTLOOK_CLIENT_SECRET", ""),
        "OUTLOOK_SENDER": os.getenv("OUTLOOK_SENDER", ""),  # user principal name (email)
        "OUTLOOK_TO": os.getenv("OUTLOOK_TO", ""),          # comma-separated
        "OUTLOOK_CC": os.getenv("OUTLOOK_CC", ""),          # optional comma-separated
        # Graph simple attachments must be < ~3 MB each; we’ll skip bigger ones
        "EMAIL_MAX_ATTACH_MB": _as_int(os.getenv("EMAIL_MAX_ATTACH_MB", "3"), 3),
    }

# Legacy convenience
ROOT_URL = config()["ROOT_URL"]
EXPLICIT_WAIT_SEC = config()["EXPLICIT_WAIT_SECONDS"]
