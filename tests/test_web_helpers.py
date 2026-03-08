from __future__ import annotations

from ima_bridge._web.answer_extractor import WebAnswerExtractor
from ima_bridge._web.conversation import WebConversationRunner
from ima_bridge._web.knowledge_base import WebKnowledgeBaseNavigator
from ima_bridge._web.session import WebSession
from ima_bridge.config import get_settings
from ima_bridge.probes import CONTENT_PREFIX, GENERIC_TARGET_URL_PATHS, INPUT_HINT
from ima_bridge.target_state import TargetStateStore


def build_components(tmp_path, monkeypatch):
    monkeypatch.setenv("IMA_MANAGED_PROFILE_DIR", str(tmp_path / "profile"))
    monkeypatch.setenv("IMA_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("IMA_WEB_PROFILE_DIR", str(tmp_path / "web-profile"))
    settings = get_settings()
    session = WebSession(settings)
    store = TargetStateStore(settings.target_url_state_path, settings.web_base_url, GENERIC_TARGET_URL_PATHS)
    navigator = WebKnowledgeBaseNavigator(settings=settings, session=session, store=store)
    extractor = WebAnswerExtractor(settings=settings, session=session)
    return settings, navigator, extractor


def test_target_score_and_persist_rules(tmp_path, monkeypatch):
    settings, navigator, _ = build_components(tmp_path, monkeypatch)
    body = f"{settings.kb_title}\n{settings.kb_owner}\n内容(5)\n输入#问题"

    assert navigator.target_score(body) >= 4
    assert navigator.has_target_signals(body) is True
    assert navigator.can_persist_target_url("https://ima.qq.com/wiki/123", body) is True
    assert navigator.can_persist_target_url("https://ima.qq.com/wikis", body) is False


def test_answer_extractor_helpers(tmp_path, monkeypatch):
    settings, _, extractor = build_components(tmp_path, monkeypatch)
    before = "header\nleft panel"
    after = f"header\nleft panel\n问题\nima\n回答内容\n\n\n\n\n{settings.mode_name}"

    assert extractor.extract_answer_text(before, after, "问题") == "回答内容"
    assert extractor.clean_ai_text("\nima\n回答A\n\n") == "回答A"
    assert extractor.extract_class_names('<div class="alpha beta"></div><span class="beta gamma"></span>') == ["alpha", "beta", "gamma"]
    assert extractor.extract_references("正文\n[1] 引用一\n[2] 引用二") == ["[1] 引用一", "[2] 引用二"]



def test_target_signals_allow_name_owner_without_full_title(tmp_path, monkeypatch):
    settings, navigator, _ = build_components(tmp_path, monkeypatch)
    body = f"{settings.kb_name}\n{settings.kb_owner}\n{CONTENT_PREFIX}5)\n{INPUT_HINT}??"

    assert settings.kb_title not in body
    assert navigator.has_target_signals(body) is True


def test_login_required_detection_matches_login_cta(tmp_path, monkeypatch):
    _, navigator, _ = build_components(tmp_path, monkeypatch)

    assert navigator.is_login_required("登录一下，即可开启你的专属知识库") is True
    assert navigator.is_login_required("登录以同步历史会话") is True



def test_conversation_runner_allows_hidden_model_badge(tmp_path, monkeypatch):
    settings, _, extractor = build_components(tmp_path, monkeypatch)
    session = WebSession(settings)
    runner = WebConversationRunner(settings=settings, session=session, extractor=extractor)

    class DummyPage:
        pass

    page = DummyPage()
    runner.session = type("Session", (), {"body_text": lambda self, page: settings.mode_name})()
    runner.find_composer = lambda page: None

    runner.ensure_mode_model(page)


def test_conversation_runner_allows_composer_without_mode_label(tmp_path, monkeypatch):
    settings, _, extractor = build_components(tmp_path, monkeypatch)
    session = WebSession(settings)
    runner = WebConversationRunner(settings=settings, session=session, extractor=extractor)

    class DummyPage:
        pass

    page = DummyPage()
    runner.session = type("Session", (), {"body_text": lambda self, page: ""})()
    runner.find_composer = lambda page: object()

    runner.ensure_mode_model(page)
