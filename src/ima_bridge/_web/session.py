from __future__ import annotations

import time

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
        current = self.current_page(context)
        if current is not None:
            return current
        return context.new_page()

    def active_pages(self, context: BrowserContext) -> list[Page]:
        try:
            candidates = list(context.pages)
        except PlaywrightError:
            return []

        active: list[Page] = []
        for page in candidates:
            try:
                if not page.is_closed():
                    active.append(page)
            except PlaywrightError:
                continue
        return active

    def current_page(self, context: BrowserContext) -> Page | None:
        pages = self.active_pages(context)
        if not pages:
            return None
        return pages[-1]

    def wait_for_page_activity(self, context: BrowserContext, timeout_ms: int) -> None:
        current = self.current_page(context)
        if current is None:
            time.sleep(timeout_ms / 1000)
            return
        try:
            current.wait_for_timeout(timeout_ms)
        except PlaywrightError:
            time.sleep(min(timeout_ms, 250) / 1000)

    def open_home(self, page: Page) -> None:
        page.set_default_timeout(int(self.settings.web_navigation_timeout_seconds * 1000))
        page.goto(self.settings.web_base_url, wait_until="domcontentloaded")
        page.wait_for_timeout(700)

    def body_text(self, page: Page) -> str:
        try:
            return page.inner_text("body").strip()
        except (TimeoutError, PlaywrightError):
            return ""

    def body_html(self, page: Page) -> str:
        try:
            return page.inner_html("body")
        except (TimeoutError, PlaywrightError):
            return ""
