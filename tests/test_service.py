from __future__ import annotations

from dataclasses import dataclass

from ima_bridge.config import Settings
from ima_bridge.driver_protocol import DriverAskResult, DriverHealthStatus, DriverLoginStatus
from ima_bridge.errors import BridgeError
from ima_bridge.service import IMAAskService


@dataclass
class FakeDriver:
    health_result: DriverHealthStatus
    login_result: DriverLoginStatus
    ask_result: DriverAskResult | None = None
    ask_error: Exception | None = None

    def health(self) -> DriverHealthStatus:
        return self.health_result

    def login(self, timeout_seconds: float | None = None) -> DriverLoginStatus:
        return self.login_result

    def ask(self, question: str, on_update=None) -> DriverAskResult:
        if self.ask_error is not None:
            raise self.ask_error
        assert self.ask_result is not None
        if on_update is not None:
            on_update("片段", "完整片段")
        return self.ask_result


def make_settings() -> Settings:
    return Settings(driver_mode="web")


def test_service_uses_driver_protocol_for_health_and_login():
    settings = make_settings()
    driver = FakeDriver(
        health_result=DriverHealthStatus(ok=True, source_driver="web", base_url="https://ima.qq.com/", profile_dir="profile"),
        login_result=DriverLoginStatus(ok=True, base_url="https://ima.qq.com/", profile_dir="profile", timeout_seconds=30),
        ask_result=DriverAskResult(source_driver="web", answer_text="ok"),
    )
    service = IMAAskService(settings=settings, driver=driver)

    health = service.health()
    login = service.login(timeout_seconds=30)

    assert health.ok is True
    assert health.source_driver == "web"
    assert health.instance == settings.instance
    assert login.ok is True
    assert login.profile_dir == "profile"


def test_service_maps_bridge_error_for_ask():
    settings = make_settings()
    driver = FakeDriver(
        health_result=DriverHealthStatus(ok=True, source_driver="web"),
        login_result=DriverLoginStatus(ok=True, base_url="https://ima.qq.com/", profile_dir="profile", timeout_seconds=30),
        ask_error=BridgeError("ASK_TIMEOUT", "too slow"),
    )
    service = IMAAskService(settings=settings, driver=driver)

    response = service.ask("hello")

    assert response.ok is False
    assert response.error_code == "ASK_TIMEOUT"
    assert response.error_message == "too slow"


def test_service_streaming_callback_and_fallback_error_mapping():
    settings = make_settings()
    driver = FakeDriver(
        health_result=DriverHealthStatus(ok=True, source_driver="web"),
        login_result=DriverLoginStatus(ok=True, base_url="https://ima.qq.com/", profile_dir="profile", timeout_seconds=30),
        ask_result=DriverAskResult(source_driver="web", answer_text="final", answer_html="<p>final</p>", references=["[1] ref"]),
    )
    service = IMAAskService(settings=settings, driver=driver)
    updates: list[tuple[str, str]] = []

    response = service.ask_with_updates("hello", on_update=lambda delta, text: updates.append((delta, text)))

    assert response.ok is True
    assert updates == [("片段", "完整片段")]
    assert response.answer_text == "final"

