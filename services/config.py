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
        "ROOT_URL": sap_url,
        "SAP_USERNAME": os.getenv("SAP_USERNAME", ""),
        "SAP_PASSWORD": os.getenv("SAP_PASSWORD", ""),

        "HEADLESS": _as_bool(os.getenv("HEADLESS", "false")),
        "EXPLICIT_WAIT_SECONDS": _as_int(os.getenv("EXPLICIT_WAIT_SECONDS", "30"), 30),
        "PAGELOAD_TIMEOUT_SECONDS": _as_int(os.getenv("PAGELOAD_TIMEOUT_SECONDS", "90"), 90),
        "KEEP_BROWSER": _as_bool(os.getenv("KEEP_BROWSER", "true")),

        # Multithreading / pacing
        "NUM_WORKERS": _as_int(os.getenv("NUM_WORKERS", "4"), 4),
        "LOGIN_CONCURRENCY": _as_int(os.getenv("LOGIN_CONCURRENCY", "2"), 2),
        "WATCHDOG_SECONDS": _as_int(os.getenv("WATCHDOG_SECONDS", "2000"), 2000),
        "CHROME_USER_DATA_BASE": os.getenv("CHROME_USER_DATA_BASE", "chrome_profile"),

        # Reporting
        "REPORTS_DIR": os.getenv("REPORTS_DIR", "reports"),
        "DAILY_REPORTS_ENABLED": _as_bool(os.getenv("DAILY_REPORTS_ENABLED", "true")),
        "NUM_LIVE_TRACKERS": _as_int(os.getenv("NUM_LIVE_TRACKERS", "8"), 8),  # keep last N live trackers

        # Email (Outlook via Microsoft Graph)
        "EMAIL_ENABLED": _as_bool(os.getenv("EMAIL_ENABLED", "false")),
        "OUTLOOK_TENANT_ID": os.getenv("OUTLOOK_TENANT_ID", ""),
        "OUTLOOK_CLIENT_ID": os.getenv("OUTLOOK_CLIENT_ID", ""),
        "OUTLOOK_CLIENT_SECRET": os.getenv("OUTLOOK_CLIENT_SECRET", ""),
        "OUTLOOK_SENDER": os.getenv("OUTLOOK_SENDER", ""),
        "OUTLOOK_TO": os.getenv("OUTLOOK_TO", ""),
        "OUTLOOK_CC": os.getenv("OUTLOOK_CC", ""),
        "EMAIL_MAX_ATTACH_MB": _as_int(os.getenv("EMAIL_MAX_ATTACH_MB", "3"), 3),

        # Legacy lock/ retry knobs (kept)
        "LOCK_RETRY_MAX": _as_int(os.getenv("LOCK_RETRY_MAX", "3"), 3),
        "LOCK_RETRY_DELAY_SEC": _as_int(os.getenv("LOCK_RETRY_DELAY_SEC", "8"), 8),

        # Tracking
        "TRACK_DIR": os.getenv("TRACK_DIR", "WebService/TrackDrivers"),

        # Force-all-done loop
        "FORCE_ALL_DONE_ENABLED": _as_bool(os.getenv("FORCE_ALL_DONE_ENABLED", "true")),
        "FORCE_ALL_DONE_MAX_ROUNDS": _as_int(os.getenv("FORCE_ALL_DONE_MAX_ROUNDS", "25"), 25),
        "FORCE_ALL_DONE_MAX_MINUTES": _as_int(os.getenv("FORCE_ALL_DONE_MAX_MINUTES", "60"), 60),
        "FORCE_ALL_DONE_BASE_SLEEP_SEC": _as_int(os.getenv("FORCE_ALL_DONE_BASE_SLEEP_SEC", "8"), 8),

        # Page commit flow
        "LOCK_MAX_RETRIES": _as_int(os.getenv("LOCK_MAX_RETRIES", "3"), 3),
    }

# Legacy convenience
ROOT_URL = config()["ROOT_URL"]
EXPLICIT_WAIT_SEC = config()["EXPLICIT_WAIT_SECONDS"]
