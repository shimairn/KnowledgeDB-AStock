from __future__ import annotations

from dataclasses import dataclass

from ima_bridge.config import Settings
from ima_bridge.driver_protocol import DriverAskResult, DriverHealthStatus, DriverLoginStatus, DriverModelCatalog, DriverModelOption
from ima_bridge.errors import BridgeError
from ima_bridge.service import IMAAskService


@dataclass
class FakeDriver:
    health_result: DriverHealthStatus
    login_result: DriverLoginStatus
    ask_result: DriverAskResult | None = None
    ask_error: Exception | None = None
    last_model: str | None = None

    def health(self) -> DriverHealthStatus:
        return self.health_result

    def login(self, timeout_seconds: float | None = None) -> DriverLoginStatus:
        return self.login_result

    def get_model_catalog(self) -> DriverModelCatalog:
        return DriverModelCatalog(
            current_model="DeepSeek V3.2 Think",
            options=[DriverModelOption(value="DeepSeek V3.2 Think", label="DeepSeek V3.2 Think", selected=True)],
        )

    def ask(self, question: str, model: str | None = None, on_update=None) -> DriverAskResult:
        if self.ask_error is not None:
            raise self.ask_error
        assert self.ask_result is not None
        self.last_model = model
        if on_update is not None:
            on_update("answer", "chunk", "full chunk")
        return self.ask_result


def make_settings() -> Settings:
    return Settings(driver_mode="web")


def test_service_uses_driver_protocol_for_health_and_login():
    settings = make_settings()
    driver = FakeDriver(
        health_result=DriverHealthStatus(ok=True, source_driver="web", base_url="https://ima.qq.com/", profile_dir="profile"),
        login_result=DriverLoginStatus(ok=True, base_url="https://ima.qq.com/", profile_dir="profile", timeout_seconds=30),
        ask_result=DriverAskResult(source_driver="web", model="DeepSeek V3.2", answer_text="ok"),
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


def test_service_streaming_callback_and_thinking_mapping():
    settings = make_settings()
    driver = FakeDriver(
        health_result=DriverHealthStatus(ok=True, source_driver="web"),
        login_result=DriverLoginStatus(ok=True, base_url="https://ima.qq.com/", profile_dir="profile", timeout_seconds=30),
        ask_result=DriverAskResult(
            source_driver="web",
            model="DeepSeek V3.2 Think",
            thinking_text="thought",
            answer_text="final",
            answer_html="<p>final</p>",
            references=["[1] ref"],
        ),
    )
    service = IMAAskService(settings=settings, driver=driver)
    updates: list[tuple[str, str, str]] = []

    response = service.ask_with_updates(
        "hello",
        model="DeepSeek V3.2 Think",
        on_update=lambda phase, delta, text: updates.append((phase, delta, text)),
    )

    assert response.ok is True
    assert updates == [("answer", "chunk", "full chunk")]
    assert driver.last_model == "DeepSeek V3.2 Think"
    assert response.model == "DeepSeek V3.2 Think"
    assert response.thinking_text == "thought"
    assert response.answer_text == "final"
