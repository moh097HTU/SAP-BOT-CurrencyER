from core.base import Page
from services.config import config
from .elements.Username.element import Username
from .elements.Password.element import Password
from .elements.Submit.element import Submit

class LoginPage(Page):
    def go(self):
        self.open(config()["SAP_URL"])

    def login(self, username: str, password: str):
        self.go()
        Username(self.driver).set(username)
        Password(self.driver).set(password)
        Submit(self.driver).click()
        # Post-click, S/4HANA may keep same URL but replace DOM; verification is in services.ui
