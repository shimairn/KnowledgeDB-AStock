from ima_bridge.errors import CaptureFailedError, LoginRequiredError
from ima_bridge.schemas import AskResponse, DriverHealth, KnowledgeBaseIdentity
from ima_bridge.service import IMABridgeService


class FakeDriver:
    def __init__(self, source_driver, result=None, error=None):
        self.source_driver = source_driver
        self._result = result
        self._error = error

    def health(self):
        return DriverHealth(name=self.source_driver, available=True, detail="ok")

    def ask(self, question):
        if self._error:
            raise self._error
        return self._result


def test_service_falls_back_from_app_to_web(settings_fixture):
    service = IMABridgeService(settings_fixture)
    expected = AskResponse(
        ok=True,
        question="q",
        knowledge_base=KnowledgeBaseIdentity(name="爱分享", owner="购物小助手", title="【爱分享】的财经资讯"),
        mode="对话模式",
        model="DS V3.2",
        source_driver="web_fallback",
        answer_text="answer",
        answer_html="<div>answer</div>",
    )
    service.app_driver = FakeDriver("app", error=CaptureFailedError("fallback", can_fallback=True))
    service.web_driver = FakeDriver("web_fallback", result=expected)
    result = service.ask_once("q")
    assert result.ok is True
    assert result.source_driver == "web_fallback"


def test_service_returns_standardized_error(settings_fixture):
    service = IMABridgeService(settings_fixture)
    service.app_driver = FakeDriver("app", error=CaptureFailedError("fallback", can_fallback=True))
    service.web_driver = FakeDriver("web_fallback", error=LoginRequiredError("need login"))
    result = service.ask_once("q")
    assert result.ok is False
    assert result.error_code == "LOGIN_REQUIRED"
    assert result.source_driver == "web_fallback"
