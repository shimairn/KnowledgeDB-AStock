from __future__ import annotations

import json

from fastapi.testclient import TestClient

from ima_bridge.chat_ui import create_chat_ui_app
from ima_bridge.config import get_settings
from ima_bridge.driver_protocol import DriverModelCatalog, DriverModelOption
from ima_bridge.schemas import AskResponse, KnowledgeBaseIdentity, LoginResponse
from ima_bridge.ui_rate_limit import UIRateLimiter


def _configure_env(tmp_path, monkeypatch, *, trust_proxy: bool = False, rate_limit: int = 12, max_concurrent: int = 2) -> None:
    monkeypatch.setenv("IMA_MANAGED_PROFILE_ROOT", str(tmp_path / "profiles"))
    monkeypatch.setenv("IMA_WEB_PROFILE_ROOT", str(tmp_path / "web-profiles"))
    monkeypatch.setenv("IMA_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("IMA_UI_RATE_LIMIT_PER_MINUTE", str(rate_limit))
    monkeypatch.setenv("IMA_UI_MAX_CONCURRENT_PER_IP", str(max_concurrent))
    monkeypatch.setenv("IMA_UI_TRUST_PROXY", "1" if trust_proxy else "0")


def _make_settings(tmp_path, monkeypatch, **kwargs):
    _configure_env(tmp_path, monkeypatch, **kwargs)
    return get_settings(instance="ui-test", driver_mode="web")


def _make_ask_response(
    question: str,
    *,
    ok: bool = True,
    answer_text: str = "final",
    answer_html: str = "<p>final</p>",
    thinking_text: str = "",
) -> AskResponse:
    kb = KnowledgeBaseIdentity(name="Knowledge", owner="Assistant", title="Knowledge Base")
    return AskResponse(
        ok=ok,
        question=question,
        knowledge_base=kb,
        mode="chat",
        model="DS V3.2 T",
        source_driver="web",
        thinking_text=thinking_text,
        answer_text=answer_text,
        answer_html=answer_html,
        error_code=None if ok else "LOGIN_REQUIRED",
        error_message=None if ok else "login required",
    )


class FakeWorkerService:
    def __init__(
        self,
        *,
        stream_error: Exception | None = None,
        stream_updates: list[object] | None = None,
        response: AskResponse | None = None,
        model_catalog: DriverModelCatalog | None = None,
    ) -> None:
        self.stream_error = stream_error
        self.stream_updates = stream_updates or [{"phase": "answer_html", "html": "<p>chunk</p>"}]
        self.response = response
        self.model_catalog = model_catalog or DriverModelCatalog(
            current_model="DeepSeek V3.2 Think",
            options=[
                DriverModelOption(
                    value="DeepSeek V3.2 Think",
                    label="DeepSeek V3.2 Think",
                    description="更适合复杂推理",
                    selected=True,
                ),
                DriverModelOption(
                    value="DeepSeek V3.2",
                    label="DeepSeek V3.2",
                    description="更适合直接回答",
                    selected=False,
                ),
            ],
        )
        self.last_model: str | None = None

    def get_model_catalog(self) -> DriverModelCatalog:
        return self.model_catalog

    def ask(self, question: str, model: str | None = None) -> AskResponse:
        self.last_model = model
        return self.response or _make_ask_response(question)

    def ask_with_updates(self, question: str, model: str | None = None, on_update=None) -> AskResponse:
        self.last_model = model
        if on_update is not None:
            for update in self.stream_updates:
                if isinstance(update, dict):
                    on_update(update)
                else:
                    on_update(*update)
        if self.stream_error is not None:
            raise self.stream_error
        return self.response or _make_ask_response(question)

    def login(self, timeout_seconds: float | None = None) -> LoginResponse:
        return LoginResponse(
            ok=True,
            instance="ui-test",
            base_url="https://ima.qq.com/",
            profile_dir="profile",
            timeout_seconds=timeout_seconds or 180,
        )


class FakePoolManager:
    def __init__(self, *, worker=None, payload=None) -> None:
        self.worker = worker
        self.refresh_calls = 0
        self.payload = payload or {
            "ok": True,
            "status": "ready",
            "warming_up": False,
            "refresh_in_progress": False,
            "instance": "pool",
            "source_driver": "web",
            "cdp_port": None,
            "cdp_endpoint": None,
            "cdp_ready": None,
            "base_url": "https://ima.qq.com/",
            "profile_dir": None,
            "headless": True,
            "app_executable": None,
            "managed_profile_dir": "managed",
            "error_code": None,
            "error_message": None,
            "pool": {
                "workers_total": 1,
                "workers_warming": 0,
                "workers_ready": 1,
                "workers_busy": 0,
                "workers_login_required": 0,
                "workers_error": 0,
                "capacity_available": True,
            },
        }

    def refresh_all(self) -> None:
        self.refresh_calls += 1
        return None

    def summarize(self):
        pool = self.payload["pool"]
        return type("Summary", (), pool)()

    def health_payload(self) -> dict:
        return dict(self.payload)

    def get_model_catalog(self) -> DriverModelCatalog:
        if self.worker is not None:
            return self.worker.service.get_model_catalog()
        return DriverModelCatalog()

    def try_acquire(self):
        worker = self.worker
        self.worker = None
        return worker

    def release(self, worker, response=None, exc=None):
        return "ready"


def test_chat_ui_serves_static_index_and_assets(tmp_path, monkeypatch):
    settings = _make_settings(tmp_path, monkeypatch)
    service = type("Service", (), {"settings": settings})()
    worker = type("Worker", (), {"worker_id": "worker-01", "service": FakeWorkerService()})()
    client = TestClient(create_chat_ui_app(service=service, pool_manager=FakePoolManager(worker=worker)))

    index_response = client.get("/")
    js_response = client.get("/assets/app.js")
    main_response = client.get("/assets/app-main.js")
    render_response = client.get("/assets/app-render.js")
    view_response = client.get("/assets/app-view.js")

    assert index_response.status_code == 200
    assert 'type="module"' in index_response.text
    assert 'id="statusText"' in index_response.text
    assert 'id="kbLabel"' in index_response.text
    assert 'id="emptyState"' in index_response.text
    assert 'id="newConversationBtn"' in index_response.text
    assert 'id="conversationViewport"' in index_response.text
    assert 'id="modelMenu"' not in index_response.text
    assert 'id="modelMenuList"' not in index_response.text
    assert 'id="appSidebar"' not in index_response.text
    assert 'id="sidebarToggleBtn"' not in index_response.text
    assert 'id="sourceDrawer"' not in index_response.text
    assert 'id="questionMeta"' not in index_response.text
    assert 'id="thinkingToggle"' not in index_response.text
    assert 'id="poolSummary"' not in index_response.text
    composer_markup = index_response.text.split('<form id="composer"', 1)[1]
    assert "<header" in index_response.text
    assert 'id="modelSelect"' not in index_response.text
    assert 'id="clearBtn"' not in index_response.text
    assert 'id="modelMenu"' not in composer_markup
    assert 'id="sendBtn"' in composer_markup
    assert 'id="newConversationBtn"' in composer_markup

    assert js_response.status_code == 200
    assert main_response.status_code == 200
    assert render_response.status_code == 404
    assert view_response.status_code == 404
    assert "/assets/app-main.js" in js_response.text
    assert "modelMenu" not in main_response.text
    assert "scheduleHealthRefresh" in main_response.text
    assert "createRichTypewriter" in main_response.text
    assert "createMessageRenderer" not in main_response.text
    assert "prepareAnswerRender" not in main_response.text


def test_chat_ui_ui_config_and_health_are_anonymous(tmp_path, monkeypatch):
    settings = _make_settings(tmp_path, monkeypatch)
    service = type("Service", (), {"settings": settings})()
    worker = type("Worker", (), {"worker_id": "worker-01", "service": FakeWorkerService()})()
    client = TestClient(create_chat_ui_app(service=service, pool_manager=FakePoolManager(worker=worker)))

    config_response = client.get("/api/ui-config")
    health_response = client.get("/api/health")

    assert config_response.status_code == 200
    assert config_response.json()["auth_required"] is False
    assert config_response.json()["workers_total"] == 1
    assert config_response.json()["health"]["status"] == "ready"
    assert config_response.json()["startup_poll_interval_ms"] > 0
    assert config_response.json()["steady_poll_interval_ms"] > config_response.json()["startup_poll_interval_ms"]
    assert config_response.json()["kb_label"] == settings.kb_label
    assert config_response.json()["current_model"] == "DeepSeek V3.2 Think"
    assert config_response.json()["model_options"][0]["label"] == "DeepSeek V3.2 Think"
    assert health_response.status_code == 200
    assert health_response.json()["ok"] is True
    assert client.app.state.pool_manager.refresh_calls == 0


def test_chat_ui_does_not_expose_legacy_auth_endpoints(tmp_path, monkeypatch):
    settings = _make_settings(tmp_path, monkeypatch)
    service = type("Service", (), {"settings": settings})()
    worker = type("Worker", (), {"worker_id": "worker-01", "service": FakeWorkerService()})()
    client = TestClient(create_chat_ui_app(service=service, pool_manager=FakePoolManager(worker=worker)))

    assert client.post("/auth/login", json={"secret": "ignored"}).status_code == 404
    assert client.get("/auth/me").status_code == 404
    assert client.post("/auth/logout").status_code == 404
    assert client.post("/api/login", json={"timeout": 12}).status_code == 404


def test_chat_ui_stream_success_sequence(tmp_path, monkeypatch):
    settings = _make_settings(tmp_path, monkeypatch)
    service = type("Service", (), {"settings": settings})()
    worker = type("Worker", (), {"worker_id": "worker-01", "service": FakeWorkerService()})()
    client = TestClient(create_chat_ui_app(service=service, pool_manager=FakePoolManager(worker=worker)))

    index_response = client.get("/")
    config_response = client.get("/api/ui-config")
    health_response = client.get("/api/health")
    with client.stream("POST", "/api/ask-stream", json={"question": "hello"}) as response:
        events = [json.loads(line) for line in response.iter_lines() if line]

    assert index_response.status_code == 200
    assert config_response.status_code == 200
    assert health_response.status_code == 200
    assert response.status_code == 200
    assert [event["type"] for event in events] == ["start", "answer_html", "done"]
    assert events[1]["html"] == "<p>chunk</p>"
    assert events[-1]["response"]["answer_html"] == "<p>final</p>"
    assert events[-1]["response"]["thinking_text"] == ""


def test_chat_ui_stream_emits_thinking_and_done_payload(tmp_path, monkeypatch):
    settings = _make_settings(tmp_path, monkeypatch)
    service = type("Service", (), {"settings": settings})()
    worker = type(
        "Worker",
        (),
        {
            "worker_id": "worker-01",
            "service": FakeWorkerService(
                stream_updates=[
                    ("thinking", "thought", "thought"),
                    ("thinking", " more", "thought more"),
                    {"phase": "answer_html", "html": "<p>answer</p>"},
                ],
                response=_make_ask_response("hello", answer_text="answer", thinking_text="thought more"),
            ),
        },
    )()
    client = TestClient(create_chat_ui_app(service=service, pool_manager=FakePoolManager(worker=worker)))

    with client.stream("POST", "/api/ask-stream", json={"question": "hello"}) as response:
        events = [json.loads(line) for line in response.iter_lines() if line]

    assert response.status_code == 200
    assert [event["type"] for event in events] == ["start", "thinking_delta", "thinking_delta", "answer_html", "done"]
    assert events[3]["html"] == "<p>answer</p>"
    assert events[-1]["response"]["thinking_text"] == "thought more"


def test_chat_ui_forwards_selected_model_to_service(tmp_path, monkeypatch):
    settings = _make_settings(tmp_path, monkeypatch)
    service = type("Service", (), {"settings": settings})()
    fake_service = FakeWorkerService(response=_make_ask_response("hello", answer_text="answer"))
    worker = type("Worker", (), {"worker_id": "worker-01", "service": fake_service})()
    client = TestClient(create_chat_ui_app(service=service, pool_manager=FakePoolManager(worker=worker)))

    response = client.post("/api/ask", json={"question": "hello", "model": "DeepSeek V3.2"})

    assert response.status_code == 200
    assert fake_service.last_model == "DeepSeek V3.2"


def test_chat_ui_sanitizes_noise_in_ui_responses(tmp_path, monkeypatch):
    settings = _make_settings(tmp_path, monkeypatch)
    service = type("Service", (), {"settings": settings})()
    fake_service = FakeWorkerService(
        response=_make_ask_response(
            "hello",
            answer_text="找到 3 条知识库内容\n\n正式回答",
            answer_html="<p>找到 3 条知识库内容</p><p>正式回答</p><table><tr><td>3</td></tr></table>",
        )
    )
    worker = type("Worker", (), {"worker_id": "worker-01", "service": fake_service})()
    client = TestClient(create_chat_ui_app(service=service, pool_manager=FakePoolManager(worker=worker)))

    response = client.post("/api/ask", json={"question": "hello"})

    assert response.status_code == 200
    assert response.json()["answer_text"] == "正式回答"
    assert "找到 3 条知识库内容" not in response.json()["answer_html"]
    assert "<table>" in response.json()["answer_html"]


def test_chat_ui_stream_done_payload_is_cleaned(tmp_path, monkeypatch):
    settings = _make_settings(tmp_path, monkeypatch)
    service = type("Service", (), {"settings": settings})()
    fake_service = FakeWorkerService(
        stream_updates=[{"phase": "answer_html", "html": "<div>共找到 2 条相关内容</div><p>答案正文</p>"}],
        response=_make_ask_response(
            "hello",
            answer_text="共找到 2 条相关内容\n\n答案正文",
            answer_html="<div>共找到 2 条相关内容</div><p>答案正文</p><blockquote>引用说明</blockquote>",
        ),
    )
    worker = type("Worker", (), {"worker_id": "worker-01", "service": fake_service})()
    client = TestClient(create_chat_ui_app(service=service, pool_manager=FakePoolManager(worker=worker)))

    with client.stream("POST", "/api/ask-stream", json={"question": "hello"}) as response:
        events = [json.loads(line) for line in response.iter_lines() if line]

    assert response.status_code == 200
    assert events[-1]["type"] == "done"
    assert events[1]["type"] == "answer_html"
    assert "共找到 2 条相关内容" not in events[1]["html"]
    assert events[-1]["response"]["answer_text"] == "答案正文"
    assert "共找到 2 条相关内容" not in events[-1]["response"]["answer_html"]
    assert "<blockquote>" in events[-1]["response"]["answer_html"]


def test_chat_ui_stream_error_after_thinking_emits_error(tmp_path, monkeypatch):
    settings = _make_settings(tmp_path, monkeypatch)
    service = type("Service", (), {"settings": settings})()
    worker = type(
        "Worker",
        (),
        {
            "worker_id": "worker-01",
            "service": FakeWorkerService(
                stream_updates=[("thinking", "thought", "thought")],
                stream_error=RuntimeError("boom"),
            ),
        },
    )()
    client = TestClient(create_chat_ui_app(service=service, pool_manager=FakePoolManager(worker=worker)))

    with client.stream("POST", "/api/ask-stream", json={"question": "hello"}) as response:
        events = [json.loads(line) for line in response.iter_lines() if line]

    assert response.status_code == 200
    assert [event["type"] for event in events] == ["start", "thinking_delta", "error"]
    assert events[-1]["error_code"] == "CAPTURE_FAILED"


def test_chat_ui_busy_returns_429(tmp_path, monkeypatch):
    settings = _make_settings(tmp_path, monkeypatch)
    service = type("Service", (), {"settings": settings})()
    pool = FakePoolManager(
        worker=None,
        payload={
            "ok": False,
            "status": "busy",
            "warming_up": False,
            "refresh_in_progress": False,
            "instance": "pool",
            "source_driver": "web",
            "cdp_port": None,
            "cdp_endpoint": None,
            "cdp_ready": None,
            "base_url": "https://ima.qq.com/",
            "profile_dir": None,
            "headless": True,
            "app_executable": None,
            "managed_profile_dir": "managed",
            "error_code": "BUSY",
            "error_message": "No idle worker available",
            "pool": {
                "workers_total": 1,
                "workers_warming": 0,
                "workers_ready": 0,
                "workers_busy": 1,
                "workers_login_required": 0,
                "workers_error": 0,
                "capacity_available": False,
            },
        },
    )
    client = TestClient(create_chat_ui_app(service=service, pool_manager=pool))

    response = client.post("/api/ask-stream", json={"question": "hello"})

    assert response.status_code == 429
    assert response.json()["error_code"] == "BUSY"


def test_chat_ui_warming_up_returns_503(tmp_path, monkeypatch):
    settings = _make_settings(tmp_path, monkeypatch)
    service = type("Service", (), {"settings": settings})()
    pool = FakePoolManager(
        worker=None,
        payload={
            "ok": False,
            "status": "warming",
            "warming_up": True,
            "refresh_in_progress": True,
            "instance": "pool",
            "source_driver": "web",
            "cdp_port": None,
            "cdp_endpoint": None,
            "cdp_ready": None,
            "base_url": "https://ima.qq.com/",
            "profile_dir": None,
            "headless": True,
            "app_executable": None,
            "managed_profile_dir": "managed",
            "error_code": "WARMING_UP",
            "error_message": "Workers are still initializing",
            "pool": {
                "workers_total": 1,
                "workers_warming": 1,
                "workers_ready": 0,
                "workers_busy": 0,
                "workers_login_required": 0,
                "workers_error": 0,
                "capacity_available": False,
            },
        },
    )
    client = TestClient(create_chat_ui_app(service=service, pool_manager=pool))

    response = client.post("/api/ask-stream", json={"question": "hello"})

    assert response.status_code == 503
    assert response.json()["error_code"] == "WARMING_UP"


def test_chat_ui_rate_limited_returns_429(tmp_path, monkeypatch):
    settings = _make_settings(tmp_path, monkeypatch, trust_proxy=True, rate_limit=1, max_concurrent=2)
    service = type("Service", (), {"settings": settings})()
    worker = type("Worker", (), {"worker_id": "worker-01", "service": FakeWorkerService()})()
    client = TestClient(
        create_chat_ui_app(
            service=service,
            pool_manager=FakePoolManager(worker=worker),
            rate_limiter=UIRateLimiter(per_minute=1, max_concurrent_per_ip=2),
        )
    )

    first = client.post("/api/ask", json={"question": "first"}, headers={"X-Forwarded-For": "1.1.1.1"})
    second = client.post("/api/ask", json={"question": "second"}, headers={"X-Forwarded-For": "1.1.1.1"})

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json()["error_code"] == "RATE_LIMITED"


def test_chat_ui_empty_question_is_400(tmp_path, monkeypatch):
    settings = _make_settings(tmp_path, monkeypatch)
    service = type("Service", (), {"settings": settings})()
    worker = type("Worker", (), {"worker_id": "worker-01", "service": FakeWorkerService()})()
    client = TestClient(create_chat_ui_app(service=service, pool_manager=FakePoolManager(worker=worker)))

    response = client.post("/api/ask-stream", json={"question": "   "})

    assert response.status_code == 400
    assert response.json()["error_code"] == "ASK_TIMEOUT"
