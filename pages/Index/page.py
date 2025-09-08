# pages/Index/page.py
from core.base import Page
from services.ui import wait_ui5_idle
from .PurchasingTab.element import PurchasingTab
from .ProcurementOverviewTile.element import ProcurementOverviewTile

class IndexPage(Page):
    """Fiori Launchpad 'Shell-home' landing."""

    def ensure_home(self):
        wait_ui5_idle(self.driver)

    def to_purchasing(self):
        PurchasingTab(self.driver).click()
        wait_ui5_idle(self.driver)

    def open_procurement_overview(self):
        ProcurementOverviewTile(self.driver).click()
        wait_ui5_idle(self.driver)
