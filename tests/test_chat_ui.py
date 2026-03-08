from __future__ import annotations

import json

from fastapi.testclient import TestClient

from ima_bridge.chat_ui import create_chat_ui_app
from ima_bridge.config import get_settings
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
        stream_updates: list[tuple[str, str, str]] | None = None,
        response: AskResponse | None = None,
    ) -> None:
        self.stream_error = stream_error
        self.stream_updates = stream_updates or [("answer", "chunk", "full chunk")]
        self.response = response

    def ask(self, question: str) -> AskResponse:
        return self.response or _make_ask_response(question)

    def ask_with_updates(self, question: str, on_update=None) -> AskResponse:
        if on_update is not None:
            for update in self.stream_updates:
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

    assert index_response.status_code == 200
    assert "id=\"statusText\"" in index_response.text
    assert "id=\"poolSummary\"" not in index_response.text
    assert js_response.status_code == 200
    assert "/api/ask-stream" in js_response.text


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
    assert settings.kb_name in config_response.json()["kb_label"]
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
    assert [event["type"] for event in events] == ["start", "delta", "done"]
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
                    ("answer", "answer", "answer"),
                ],
                response=_make_ask_response("hello", answer_text="answer", thinking_text="thought more"),
            ),
        },
    )()
    client = TestClient(create_chat_ui_app(service=service, pool_manager=FakePoolManager(worker=worker)))

    with client.stream("POST", "/api/ask-stream", json={"question": "hello"}) as response:
        events = [json.loads(line) for line in response.iter_lines() if line]

    assert response.status_code == 200
    assert [event["type"] for event in events] == ["start", "thinking_delta", "thinking_delta", "delta", "done"]
    assert events[-1]["response"]["thinking_text"] == "thought more"


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
