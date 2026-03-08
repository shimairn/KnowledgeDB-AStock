from __future__ import annotations

from typing import Callable

from playwright.sync_api import sync_playwright

from ima_bridge.cdp_driver import CdpAskDriver
from ima_bridge.config import Settings, get_settings
from ima_bridge.errors import BridgeError, CaptureFailedError
from ima_bridge.managed_app import ManagedIMAApp
from ima_bridge.schemas import AskResponse, HealthResponse, KnowledgeBaseIdentity, LoginResponse
from ima_bridge.utils import now_iso
from ima_bridge.web_driver import WebAskDriver


class IMAAskService:
    def __init__(
        self,
        settings: Settings | None = None,
        runtime: ManagedIMAApp | None = None,
        driver: CdpAskDriver | None = None,
        web_driver: WebAskDriver | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.runtime = runtime or ManagedIMAApp(self.settings)
        self.driver = driver or CdpAskDriver(self.settings)
        self.web_driver = web_driver or WebAskDriver(self.settings)

    def health(self) -> HealthResponse:
        if self.settings.driver_mode == "web":
            with sync_playwright() as playwright:
                ok, error_code, error_message = self.web_driver.health(playwright, headless=self.settings.web_headless)
            return HealthResponse(
                ok=ok,
                instance=self.settings.instance,
                source_driver="web",
                base_url=self.settings.web_base_url,
                profile_dir=str(self.settings.web_profile_dir.resolve()),
                headless=self.settings.web_headless,
                managed_profile_dir=str(self.settings.managed_profile_dir.resolve()),
                error_code=error_code,
                error_message=error_message,
            )

        cdp_ready, endpoint = self.runtime.status()
        return HealthResponse(
            ok=cdp_ready,
            instance=self.settings.instance,
            source_driver="app",
            cdp_port=self.settings.app_cdp_port,
            cdp_endpoint=endpoint,
            cdp_ready=cdp_ready,
            app_executable=self.settings.app_executable,
            managed_profile_dir=str(self.settings.managed_profile_dir.resolve()),
            error_code=None if cdp_ready else "CAPTURE_FAILED",
            error_message=None if cdp_ready else "CDP endpoint is not reachable yet",
        )

    def login(self, timeout_seconds: float | None = None) -> LoginResponse:
        timeout = timeout_seconds if timeout_seconds is not None else self.settings.login_timeout_seconds
        base = LoginResponse(
            ok=False,
            instance=self.settings.instance,
            base_url=self.settings.web_base_url,
            profile_dir=str(self.settings.web_profile_dir.resolve()),
            timeout_seconds=timeout,
            captured_at=now_iso(),
        )
        try:
            with sync_playwright() as playwright:
                ok, error_code, error_message = self.web_driver.login(playwright, timeout_seconds=timeout)
            return base.model_copy(
                update={
                    "ok": ok,
                    "error_code": error_code,
                    "error_message": error_message,
                    "captured_at": now_iso(),
                }
            )
        except BridgeError as exc:
            return base.model_copy(update={"error_code": exc.error_code, "error_message": exc.message, "captured_at": now_iso()})
        except Exception as exc:
            fallback = CaptureFailedError(str(exc))
            return base.model_copy(
                update={"error_code": fallback.error_code, "error_message": fallback.message, "captured_at": now_iso()}
            )

    def ask_with_updates(
        self,
        question: str,
        on_update: Callable[[str, str], None] | None = None,
    ) -> AskResponse:
        kb = KnowledgeBaseIdentity(name=self.settings.kb_name, owner=self.settings.kb_owner, title=self.settings.kb_title)
        base = AskResponse(
            ok=False,
            question=question,
            knowledge_base=kb,
            mode=self.settings.mode_name,
            model=self.settings.model_prefix,
            source_driver="web" if self.settings.driver_mode == "web" else "app",
            captured_at=now_iso(),
        )
        try:
            if self.settings.driver_mode == "web":
                with sync_playwright() as playwright:
                    if on_update is None:
                        answer_text, answer_html, references, screenshot = self.web_driver.ask(
                            playwright, question, headless=self.settings.web_headless
                        )
                    else:
                        answer_text, answer_html, references, screenshot = self.web_driver.ask_stream(
                            playwright,
                            question,
                            headless=self.settings.web_headless,
                            on_update=on_update,
                        )
            else:
                endpoint = self.runtime.ensure_ready()
                with sync_playwright() as playwright:
                    browser = playwright.chromium.connect_over_cdp(endpoint)
                    answer_text, answer_html, references, screenshot = self.driver.ask(browser, question)
                if on_update is not None and answer_text:
                    on_update(answer_text, answer_text)
            return base.model_copy(
                update={
                    "ok": True,
                    "answer_text": answer_text,
                    "answer_html": answer_html,
                    "references": references,
                    "screenshot_path": screenshot,
                    "captured_at": now_iso(),
                    "error_code": None,
                    "error_message": None,
                }
            )
        except BridgeError as exc:
            return base.model_copy(update={"error_code": exc.error_code, "error_message": exc.message})
        except Exception as exc:
            fallback = CaptureFailedError(str(exc))
            return base.model_copy(update={"error_code": fallback.error_code, "error_message": fallback.message})

    def ask(self, question: str) -> AskResponse:
        return self.ask_with_updates(question=question, on_update=None)
