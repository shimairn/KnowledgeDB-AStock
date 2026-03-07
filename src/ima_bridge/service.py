from __future__ import annotations

from ima_bridge.config import Settings, get_settings
from ima_bridge.drivers import AppDriver, WebDriver
from ima_bridge.errors import BridgeError, CaptureFailedError
from ima_bridge.schemas import AskResponse, HealthResponse, KnowledgeBaseIdentity
from ima_bridge.utils import get_logger


class IMABridgeService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.logger = get_logger("ima_bridge.service")
        self.app_driver = AppDriver(self.settings)
        self.web_driver = WebDriver(self.settings)

    def health(self) -> HealthResponse:
        return HealthResponse(
            ok=True,
            knowledge_base=self._kb_identity(),
            mode=self.settings.mode,
            model=self.settings.model,
            drivers=[self.app_driver.health(), self.web_driver.health()],
        )

    def ask_once(self, question: str) -> AskResponse:
        failures: list[BridgeError] = []
        for driver in [self.app_driver, self.web_driver]:
            try:
                return driver.ask(question)
            except BridgeError as exc:
                failures.append(exc)
                self.logger.warning("driver %s failed: %s %s", driver.source_driver, exc.error_code, exc.message)
                if exc.can_fallback and driver.source_driver != self.web_driver.source_driver:
                    continue
                return self._error_response(question, driver.source_driver, exc)
            except Exception as exc:
                wrapped = CaptureFailedError(str(exc), can_fallback=driver.source_driver != self.web_driver.source_driver)
                failures.append(wrapped)
                self.logger.exception("unexpected failure in %s", driver.source_driver)
                if wrapped.can_fallback and driver.source_driver != self.web_driver.source_driver:
                    continue
                return self._error_response(question, driver.source_driver, wrapped)
        last = failures[-1] if failures else CaptureFailedError("未知错误")
        return self._error_response(question, self.web_driver.source_driver, last)

    def _kb_identity(self) -> KnowledgeBaseIdentity:
        return KnowledgeBaseIdentity(
            name=self.settings.kb_name,
            owner=self.settings.kb_owner,
            title=self.settings.kb_title,
        )

    def _error_response(self, question: str, source_driver: str, exc: BridgeError) -> AskResponse:
        return AskResponse(
            ok=False,
            question=question,
            knowledge_base=self._kb_identity(),
            mode=self.settings.mode,
            model=self.settings.model,
            source_driver=source_driver if source_driver in {"app", "web_fallback"} else "web_fallback",
            error_code=exc.error_code,
            error_message=exc.message,
        )
