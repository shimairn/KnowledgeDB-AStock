from __future__ import annotations

from playwright.sync_api import BrowserContext, Error as PlaywrightError, Page, Playwright, TimeoutError

from ima_bridge.config import Settings


class WebSession:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def launch_context(self, playwright: Playwright, headless: bool) -> BrowserContext:
        kwargs = {
            "user_data_dir": str(self.settings.web_profile_dir.resolve()),
            "headless": headless,
            "viewport": {"width": 1600, "height": 1000},
            "args": ["--disable-blink-features=AutomationControlled"],
        }
        if self.settings.web_channel:
            kwargs["channel"] = self.settings.web_channel

        try:
            return playwright.chromium.launch_persistent_context(**kwargs)
        except PlaywrightError:
            kwargs.pop("channel", None)
            return playwright.chromium.launch_persistent_context(**kwargs)

    def acquire_page(self, context: BrowserContext) -> Page:
        if context.pages:
            return context.pages[0]
        return context.new_page()

    def open_home(self, page: Page) -> None:
        page.set_default_timeout(int(self.settings.web_navigation_timeout_seconds * 1000))
        page.goto(self.settings.web_base_url, wait_until="domcontentloaded")
        page.wait_for_timeout(700)

    def body_text(self, page: Page) -> str:
        try:
            return page.inner_text("body").strip()
        except TimeoutError:
            return ""

    def body_html(self, page: Page) -> str:
        try:
            return page.inner_html("body")
        except TimeoutError:
            return ""
