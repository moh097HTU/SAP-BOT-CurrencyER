from fastapi import APIRouter
from services.driver import get_driver
from services.auth import login
from services.config import config
from services.ui import wait_for_shell_home

router = APIRouter()

@router.get("/auth/test-login")
async def test_login():
    cfg = config()
    driver = get_driver(headless=cfg["HEADLESS"])
    try:
        login(driver)
        ok = wait_for_shell_home(driver, timeout=cfg["EXPLICIT_WAIT_SECONDS"])
        return {
            "ok": ok,
            "current_url": driver.current_url,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        if not cfg["KEEP_BROWSER"]:
            driver.quit()
