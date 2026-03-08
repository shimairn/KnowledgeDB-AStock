from __future__ import annotations

from typing import Callable

from ima_bridge.config import Settings, get_settings
from ima_bridge.driver_adapters import LegacyAppServiceDriver, WebServiceDriver
from ima_bridge.driver_protocol import AskDriver
from ima_bridge.errors import BridgeError, CaptureFailedError
from ima_bridge.cdp_driver import CdpAskDriver
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
        self.ask_driver = self._resolve_driver(driver=self.driver, runtime=self.runtime, web_driver=self.web_driver)

    def _resolve_driver(
        self,
        driver: CdpAskDriver | AskDriver,
        runtime: ManagedIMAApp,
        web_driver: WebAskDriver,
    ) -> AskDriver:
        if hasattr(driver, "health") and hasattr(driver, "login"):
            return driver  # type: ignore[return-value]
        if self.settings.driver_mode == "web":
            return WebServiceDriver(settings=self.settings, web_driver=web_driver)
        return LegacyAppServiceDriver(
            settings=self.settings,
            runtime=runtime,
            driver=driver if isinstance(driver, CdpAskDriver) else None,
            login_driver=WebServiceDriver(settings=self.settings, web_driver=web_driver),
        )

    def health(self) -> HealthResponse:
        try:
            status = self.ask_driver.health()
            return HealthResponse(
                ok=status.ok,
                instance=self.settings.instance,
                source_driver=status.source_driver,
                cdp_port=status.cdp_port,
                cdp_endpoint=status.cdp_endpoint,
                cdp_ready=status.cdp_ready,
                base_url=status.base_url,
                profile_dir=status.profile_dir,
                headless=status.headless,
                app_executable=status.app_executable,
                managed_profile_dir=status.managed_profile_dir or str(self.settings.managed_profile_dir.resolve()),
                error_code=status.error_code,
                error_message=status.error_message,
            )
        except BridgeError as exc:
            return HealthResponse(
                ok=False,
                instance=self.settings.instance,
                source_driver="web" if self.settings.driver_mode == "web" else "app",
                managed_profile_dir=str(self.settings.managed_profile_dir.resolve()),
                error_code=exc.error_code,
                error_message=exc.message,
            )
        except Exception as exc:
            fallback = CaptureFailedError(str(exc))
            return HealthResponse(
                ok=False,
                instance=self.settings.instance,
                source_driver="web" if self.settings.driver_mode == "web" else "app",
                managed_profile_dir=str(self.settings.managed_profile_dir.resolve()),
                error_code=fallback.error_code,
                error_message=fallback.message,
            )

    def login(self, timeout_seconds: float | None = None) -> LoginResponse:
        timeout = timeout_seconds if timeout_seconds is not None else self.settings.login_timeout_seconds
        try:
            status = self.ask_driver.login(timeout_seconds=timeout)
            return LoginResponse(
                ok=status.ok,
                instance=self.settings.instance,
                source_driver="web",
                base_url=status.base_url or self.settings.web_base_url,
                profile_dir=status.profile_dir or str(self.settings.web_profile_dir.resolve()),
                timeout_seconds=status.timeout_seconds or timeout,
                captured_at=now_iso(),
                error_code=status.error_code,
                error_message=status.error_message,
            )
        except BridgeError as exc:
            return LoginResponse(
                ok=False,
                instance=self.settings.instance,
                base_url=self.settings.web_base_url,
                profile_dir=str(self.settings.web_profile_dir.resolve()),
                timeout_seconds=timeout,
                captured_at=now_iso(),
                error_code=exc.error_code,
                error_message=exc.message,
            )
        except Exception as exc:
            fallback = CaptureFailedError(str(exc))
            return LoginResponse(
                ok=False,
                instance=self.settings.instance,
                base_url=self.settings.web_base_url,
                profile_dir=str(self.settings.web_profile_dir.resolve()),
                timeout_seconds=timeout,
                captured_at=now_iso(),
                error_code=fallback.error_code,
                error_message=fallback.message,
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
            result = self.ask_driver.ask(question=question, on_update=on_update)
            return base.model_copy(
                update={
                    "ok": True,
                    "source_driver": result.source_driver,
                    "answer_text": result.answer_text,
                    "answer_html": result.answer_html,
                    "references": result.references,
                    "screenshot_path": result.screenshot_path,
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
