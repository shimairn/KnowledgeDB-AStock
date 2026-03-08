from __future__ import annotations

from typing import Callable

from playwright.sync_api import sync_playwright

from ima_bridge.cdp_driver import CdpAskDriver
from ima_bridge.config import Settings
from ima_bridge.driver_protocol import AskDriver, DriverAskResult, DriverHealthStatus, DriverLoginStatus
from ima_bridge.managed_app import ManagedIMAApp
from ima_bridge.probes import APP_DRIVER_DEPRECATION_MESSAGE
from ima_bridge.utils import get_logger
from ima_bridge.web_driver import WebAskDriver


class WebServiceDriver(AskDriver):
    source_driver = "web"

    def __init__(self, settings: Settings, web_driver: WebAskDriver | None = None) -> None:
        self.settings = settings
        self.web_driver = web_driver or WebAskDriver(settings)

    def health(self) -> DriverHealthStatus:
        with sync_playwright() as playwright:
            ok, error_code, error_message = self.web_driver.health(playwright, headless=self.settings.web_headless)
        return DriverHealthStatus(
            ok=ok,
            source_driver="web",
            base_url=self.settings.web_base_url,
            profile_dir=str(self.settings.web_profile_dir.resolve()),
            headless=self.settings.web_headless,
            managed_profile_dir=str(self.settings.managed_profile_dir.resolve()),
            error_code=error_code,
            error_message=error_message,
        )

    def login(self, timeout_seconds: float | None = None) -> DriverLoginStatus:
        timeout = timeout_seconds if timeout_seconds is not None else self.settings.login_timeout_seconds
        with sync_playwright() as playwright:
            ok, error_code, error_message = self.web_driver.login(playwright, timeout_seconds=timeout)
        return DriverLoginStatus(
            ok=ok,
            source_driver="web",
            base_url=self.settings.web_base_url,
            profile_dir=str(self.settings.web_profile_dir.resolve()),
            timeout_seconds=timeout,
            error_code=error_code,
            error_message=error_message,
        )

    def ask(
        self,
        question: str,
        on_update: Callable[..., None] | None = None,
    ) -> DriverAskResult:
        with sync_playwright() as playwright:
            if on_update is None:
                answer_text, answer_html, references, screenshot, thinking_text = self.web_driver.ask(
                    playwright,
                    question,
                    headless=self.settings.web_headless,
                )
            else:
                answer_text, answer_html, references, screenshot, thinking_text = self.web_driver.ask_stream(
                    playwright,
                    question,
                    headless=self.settings.web_headless,
                    on_update=on_update,
                )
        return DriverAskResult(
            source_driver="web",
            thinking_text=thinking_text,
            answer_text=answer_text,
            answer_html=answer_html,
            references=references,
            screenshot_path=screenshot,
        )


class LegacyAppServiceDriver(AskDriver):
    source_driver = "app"

    def __init__(
        self,
        settings: Settings,
        runtime: ManagedIMAApp | None = None,
        driver: CdpAskDriver | None = None,
        login_driver: WebServiceDriver | None = None,
    ) -> None:
        self.settings = settings
        self.runtime = runtime or ManagedIMAApp(settings)
        self.driver = driver or CdpAskDriver(settings)
        self.login_driver = login_driver or WebServiceDriver(settings)
        self.logger = get_logger("ima_bridge.legacy_app_driver")
        self.logger.warning(APP_DRIVER_DEPRECATION_MESSAGE)

    def health(self) -> DriverHealthStatus:
        cdp_ready, endpoint = self.runtime.status()
        return DriverHealthStatus(
            ok=cdp_ready,
            source_driver="app",
            cdp_port=self.settings.app_cdp_port,
            cdp_endpoint=endpoint,
            cdp_ready=cdp_ready,
            app_executable=self.settings.app_executable,
            managed_profile_dir=str(self.settings.managed_profile_dir.resolve()),
            error_code=None if cdp_ready else "CAPTURE_FAILED",
            error_message=None if cdp_ready else "CDP endpoint is not reachable yet",
        )

    def login(self, timeout_seconds: float | None = None) -> DriverLoginStatus:
        return self.login_driver.login(timeout_seconds=timeout_seconds)

    def ask(
        self,
        question: str,
        on_update: Callable[..., None] | None = None,
    ) -> DriverAskResult:
        endpoint = self.runtime.ensure_ready()
        with sync_playwright() as playwright:
            browser = playwright.chromium.connect_over_cdp(endpoint)
            try:
                answer_text, answer_html, references, screenshot = self.driver.ask(browser, question)
            finally:
                browser.close()
        if on_update is not None and answer_text:
            on_update("answer", answer_text, answer_text)
        return DriverAskResult(
            source_driver="app",
            thinking_text="",
            answer_text=answer_text,
            answer_html=answer_html,
            references=references,
            screenshot_path=screenshot,
        )
