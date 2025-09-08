# run_demo.py
from services.config import config
from services.driver import get_driver
from services.auth import login
from services.ui import wait_for_shell_home, wait_ui5_idle, wait_url_contains
from pages.Index.page import IndexPage

def main():
    cfg = config()
    driver = get_driver(headless=cfg["HEADLESS"])
    try:
        print("[1/3] Logging in …")
        login(driver)

        print("[2/3] Waiting for Fiori Shell …")
        ok = wait_for_shell_home(driver, timeout=cfg["EXPLICIT_WAIT_SECONDS"])
        print(f"Shell-home detected: {ok}")
        wait_ui5_idle(driver, timeout=cfg["EXPLICIT_WAIT_SECONDS"])

        print("[3/3] Opening Purchasing → Procurement Overview …")
        idx = IndexPage(driver, root=cfg["SAP_URL"])
        idx.to_purchasing()
        idx.open_procurement_overview()
        wait_ui5_idle(driver, timeout=cfg["EXPLICIT_WAIT_SECONDS"])

        # confirm navigation by hash
        if not wait_url_contains(driver, "#Procurement-displayOverviewPage", cfg["EXPLICIT_WAIT_SECONDS"]):
            print("[WARN] Did not see target hash yet; UI might still be loading.")
        input("\n✅ Navigated. Press Enter to close…")
    finally:
        if not cfg["KEEP_BROWSER"]:
            driver.quit()

if __name__ == "__main__":
    main()
