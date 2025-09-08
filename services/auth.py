from services.config import config
from pages.Login.page import LoginPage
from services.ui import wait_for_shell_home

def login(driver) -> None:
    cfg = config()
    LoginPage(driver).login(cfg["SAP_USERNAME"], cfg["SAP_PASSWORD"])
    # Let caller verify with wait_for_shell_home
    wait_for_shell_home(driver, timeout=cfg["EXPLICIT_WAIT_SECONDS"])
