from __future__ import annotations

from playwright.sync_api import Error as PlaywrightError

from ima_bridge._web.answer_extractor import ExtractedAIContent, WebAnswerExtractor
from ima_bridge._web.conversation import WebConversationRunner, match_model_option, normalize_model_text
from ima_bridge._web.knowledge_base import WebKnowledgeBaseNavigator
from ima_bridge._web.session import WebSession
from ima_bridge.config import get_settings
from ima_bridge.driver_protocol import DriverModelOption
from ima_bridge.probes import CONTENT_PREFIX, GENERIC_TARGET_URL_PATHS, INPUT_HINT
from ima_bridge.target_state import TargetStateStore
from ima_bridge.web_driver import WebAskDriver


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
    assert extractor.extract_references("正文\n[1] 引用一\n[2] 引用二") == ["[1] 引用一", "[2] 引用二"]


def test_answer_extractor_prefers_richer_text_over_empty_kb_fallback(tmp_path, monkeypatch):
    _, _, extractor = build_components(tmp_path, monkeypatch)

    primary = "没有找到相关的知识库内容"
    secondary = "没有找到相关的知识库内容\n但根据文档，华为算力概念股包括示例 A、示例 B。"

    assert extractor._prefer_richer_answer_candidate(primary, secondary) == secondary


def test_find_latest_ai_nodes_skips_empty_tail_container(tmp_path, monkeypatch):
    _, _, extractor = build_components(tmp_path, monkeypatch)

    class DummyLocator:
        def __init__(self, items):
            self.items = list(items)

        def count(self):
            return len(self.items)

        def nth(self, index):
            return self.items[index]

    class DummyLeaf:
        def __init__(self, *, text="", html="", visible=True):
            self.text = text
            self.html = html
            self.visible = visible

        def is_visible(self):
            return self.visible

        def inner_text(self, timeout=800):
            _ = timeout
            return self.text

        def inner_html(self, timeout=800):
            _ = timeout
            return self.html

        def locator(self, _selector):
            return DummyLocator([])

    class DummyContainer(DummyLeaf):
        def __init__(self, *, text="", html="", bubble=None, message=None, visible=True):
            super().__init__(text=text, html=html, visible=visible)
            self.bubble = bubble
            self.message = message

        def locator(self, selector):
            if "_bubble_" in selector:
                return DummyLocator([self.bubble] if self.bubble is not None else [])
            if "_message_" in selector:
                return DummyLocator([self.message] if self.message is not None else [])
            return DummyLocator([])

    class DummyPage:
        def __init__(self, containers):
            self.containers = containers

        def locator(self, selector):
            if "aiContainer" in selector:
                return DummyLocator(self.containers)
            return DummyLocator([])

    valid_bubble = DummyLeaf(
        text="\u6b63\u5f0f\u56de\u7b54",
        html='<div class="_markdown_60wa1_1"><p>\u6b63\u5f0f\u56de\u7b54</p></div>',
    )
    valid_container = DummyContainer(text="\u6b63\u5f0f\u56de\u7b54", bubble=valid_bubble)
    empty_tail_bubble = DummyLeaf(html='<div id="section-anchor"></div><div></div>')
    empty_tail_container = DummyContainer(text="ima \u627e\u5230 45 \u7bc7\u77e5\u8bc6\u5e93\u8d44\u6599", bubble=empty_tail_bubble)

    container, node = extractor.find_latest_ai_nodes(DummyPage([valid_container, empty_tail_container]))

    assert container is valid_container
    assert node is valid_bubble


def test_target_signals_allow_name_owner_without_full_title(tmp_path, monkeypatch):
    settings, navigator, _ = build_components(tmp_path, monkeypatch)
    body = f"{settings.kb_name}\n{settings.kb_owner}\n{CONTENT_PREFIX}5)\n{INPUT_HINT}问题"

    assert settings.kb_title not in body
    assert navigator.has_target_signals(body) is True


def test_confirm_target_context_rejects_generic_hub_page(tmp_path, monkeypatch):
    settings, navigator, _ = build_components(tmp_path, monkeypatch)
    body = f"{settings.kb_title}\n{settings.kb_name}\n{settings.mode_name}\n问答历史"

    class DummyContext:
        def __init__(self):
            self.pages = []

    class DummyPage:
        def __init__(self, url: str, context):
            self.url = url
            self.context = context

    context = DummyContext()
    page = DummyPage("https://ima.qq.com/wikis", context)
    context.pages = [page]

    navigator.session = type("Session", (), {"body_text": lambda self, current: body})()

    assert navigator.has_target_signals(body) is True
    assert navigator.confirm_target_context(page) is False


def test_confirm_target_context_accepts_expanded_generic_kb_page(tmp_path, monkeypatch):
    settings, navigator, _ = build_components(tmp_path, monkeypatch)
    body = f"{settings.kb_title}\n{settings.kb_owner}\n{CONTENT_PREFIX}22557)\n{INPUT_HINT}问题"

    class DummyContext:
        def __init__(self):
            self.pages = []

    class DummyPage:
        def __init__(self, url: str, context):
            self.url = url
            self.context = context

    context = DummyContext()
    page = DummyPage("https://ima.qq.com/wikis", context)
    context.pages = [page]

    navigator.session = type("Session", (), {"body_text": lambda self, current: body})()
    navigator.remember_target_url = lambda page, body_text=None: None

    assert navigator.confirm_target_context(page) is True


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


def test_model_match_handles_compact_and_full_labels():
    options = [
        DriverModelOption(value="DeepSeek V3.2 Think", label="DeepSeek V3.2 Think"),
        DriverModelOption(value="DeepSeek V3.2", label="DeepSeek V3.2"),
    ]

    assert normalize_model_text("DS V3.2 T") == normalize_model_text("DeepSeek V3.2 Think")
    assert match_model_option("DS V3.2 T", options) == options[0]
    assert match_model_option("DS V3.2", options) == options[1]


def test_ensure_model_menu_closed_waits_for_overlay_to_disappear(tmp_path, monkeypatch):
    settings, _, extractor = build_components(tmp_path, monkeypatch)
    runner = WebConversationRunner(settings=settings, session=WebSession(settings), extractor=extractor)

    class DummyMenuItem:
        def __init__(self, page):
            self.page = page

        def is_visible(self):
            return self.page.menu_visible

    class DummyLocator:
        def __init__(self, page):
            self.page = page

        def count(self):
            return 1

        def nth(self, _index):
            return DummyMenuItem(self.page)

    class DummyKeyboard:
        def __init__(self, page):
            self.page = page
            self.presses = []

        def press(self, key):
            self.presses.append(key)
            if key == "Escape":
                self.page.menu_visible = False

    class DummyMouse:
        def click(self, *_args, **_kwargs):
            return None

    class DummyPage:
        def __init__(self):
            self.menu_visible = True
            self.keyboard = DummyKeyboard(self)
            self.mouse = DummyMouse()

        def locator(self, _selector):
            return DummyLocator(self)

        def wait_for_timeout(self, _timeout):
            return None

    page = DummyPage()

    assert runner._ensure_model_menu_closed(page) is True
    assert page.keyboard.presses == ["Escape"]
    assert page.menu_visible is False


def test_submit_question_closes_model_menu_before_filling(tmp_path, monkeypatch):
    settings, _, extractor = build_components(tmp_path, monkeypatch)
    runner = WebConversationRunner(settings=settings, session=WebSession(settings), extractor=extractor)
    events: list[str] = []

    class DummyKeyboard:
        def press(self, key):
            events.append(f"key:{key}")

        def type(self, text):
            events.append(f"type:{text}")

    class DummyComposer:
        def fill(self, value):
            events.append(f"fill:{value}")

        def get_attribute(self, name):
            if name == "contenteditable":
                return "true"
            return None

        def press(self, key):
            events.append(f"press:{key}")

        def is_visible(self):
            return True

        def click(self, *args, **kwargs):
            events.append("click")

        def scroll_into_view_if_needed(self, *args, **kwargs):
            return None

        def evaluate(self, _script):
            events.append("eval-click")

        def bounding_box(self):
            return {"x": 0, "y": 0, "width": 10, "height": 10}

    class DummyMouse:
        def click(self, *_args, **_kwargs):
            events.append("mouse-click")

    class DummyPage:
        def __init__(self):
            self.keyboard = DummyKeyboard()
            self.mouse = DummyMouse()

        def wait_for_timeout(self, _timeout):
            return None

        def locator(self, _selector):
            raise AssertionError("locator should not be used in this test")

    page = DummyPage()
    composer = DummyComposer()
    runner._ensure_model_menu_closed = lambda current_page, timeout_ms=1500: (events.append("ensure-closed"), True)[1]
    runner.find_composer = lambda current_page: composer
    runner.click_send_control = lambda current_page: True

    runner.submit_question(page, "hello")

    assert events[:3] == ["ensure-closed", "click", "fill:"]
    assert "fill:hello" in events


def test_web_session_returns_empty_body_for_closed_page(tmp_path, monkeypatch):
    settings, _, _ = build_components(tmp_path, monkeypatch)
    session = WebSession(settings)

    class DummyPage:
        def inner_text(self, _selector):
            raise PlaywrightError("Target page, context or browser has been closed")

        def inner_html(self, _selector):
            raise PlaywrightError("Target page, context or browser has been closed")

    page = DummyPage()

    assert session.body_text(page) == ""
    assert session.body_html(page) == ""


def test_web_driver_login_tolerates_transient_closed_page_during_poll(tmp_path, monkeypatch):
    monkeypatch.setenv("IMA_MANAGED_PROFILE_DIR", str(tmp_path / "profile"))
    monkeypatch.setenv("IMA_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("IMA_WEB_PROFILE_DIR", str(tmp_path / "web-profile"))
    settings = get_settings(driver_mode="web")
    driver = WebAskDriver(settings)

    class DummyPage:
        def __init__(self, name: str, context, *, fail_wait: bool = False):
            self.name = name
            self.context = context
            self.fail_wait = fail_wait

        def is_closed(self):
            return False

        def wait_for_timeout(self, _timeout):
            if self.fail_wait:
                self.context.show_target = True
                raise PlaywrightError("Target page, context or browser has been closed")

    class DummyContext:
        def __init__(self):
            self.show_target = False
            self.poll_page = DummyPage("poll", self, fail_wait=True)
            self.target_page = DummyPage("target", self)
            self.closed = False

        @property
        def pages(self):
            return [self.target_page] if self.show_target else [self.poll_page]

        def new_page(self):
            return self.poll_page

        def close(self):
            self.closed = True

    context = DummyContext()

    driver.session.launch_context = lambda playwright, headless=False: context
    driver.session.open_home = lambda page: None
    driver.kb_navigator.try_open_remembered_target = lambda page: False
    driver.kb_navigator.find_target_page = lambda pages: next((page for page in pages if getattr(page, "name", "") == "target"), None)
    remembered: list[str] = []
    driver.kb_navigator.remember_target_url = lambda page: remembered.append(page.name)

    ok, error_code, error_message = driver.login(playwright=None, timeout_seconds=2)

    assert ok is True
    assert error_code is None
    assert error_message is None
    assert remembered == ["target"]
    assert context.closed is True


def test_wait_answer_returns_on_stable_answer_html_even_if_page_text_keeps_changing(tmp_path, monkeypatch):
    settings, _, extractor = build_components(tmp_path, monkeypatch)
    object.__setattr__(settings, "ask_timeout_seconds", 0.05)
    object.__setattr__(settings, "poll_interval_seconds", 0.0)
    runner = WebConversationRunner(settings=settings, session=WebSession(settings), extractor=extractor)
    updates: list[tuple[tuple[object, ...], dict[str, object]]] = []

    class DummyPage:
        def wait_for_timeout(self, _timeout):
            return None

    class DummySession:
        def __init__(self):
            self.text_calls = 0
            self.html_calls = 0
            self.text_values = [
                "before\n\u601d\u8003\u4e2d 1",
                "before\n\u601d\u8003\u4e2d 2",
                "before\n\u601d\u8003\u4e2d 3",
            ]

        def body_text(self, _page):
            index = min(self.text_calls, len(self.text_values) - 1)
            self.text_calls += 1
            return self.text_values[index]

        def body_html(self, _page):
            self.html_calls += 1
            return f"<body>tick-{self.html_calls}</body>"

    class DummyExtractor:
        def __init__(self):
            self.calls = 0

        def extract_latest_ai_content(self, _page):
            self.calls += 1
            if self.calls == 1:
                return ExtractedAIContent(thinking_text="\u6b63\u5728\u5206\u6790")
            return ExtractedAIContent(
                answer_text="\u534a\u5bfc\u4f53\u8bbe\u5907\u5305\u62ec\u5149\u523b\u3001\u523b\u8680\u548c\u6c89\u79ef\u8bbe\u5907\u3002",
                answer_html="<div class=\"_markdown_60wa1_1\"><p>\u534a\u5bfc\u4f53\u8bbe\u5907\u5305\u62ec\u5149\u523b\u3001\u523b\u8680\u548c\u6c89\u79ef\u8bbe\u5907\u3002</p></div>",
                thinking_text="\u6b63\u5728\u5206\u6790",
            )

    page = DummyPage()
    runner.session = DummySession()
    runner.extractor = DummyExtractor()

    latest_text, latest_html = runner.wait_answer(
        page,
        before_text="before",
        question="\u4ecb\u7ecd\u534a\u5bfc\u4f53\u8bbe\u5907",
        on_update=lambda *args, **kwargs: updates.append((args, kwargs)),
    )

    assert latest_text.endswith("\u601d\u8003\u4e2d 3")
    assert latest_html == "<body>tick-4</body>"
    assert any(args and isinstance(args[0], dict) and args[0].get("phase") == "answer_html" for args, _ in updates)
