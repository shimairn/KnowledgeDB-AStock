from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from contextlib import contextmanager
from types import SimpleNamespace

from ima_bridge.chat_ui import create_chat_ui_server
from ima_bridge.schemas import AskResponse, HealthResponse, KnowledgeBaseIdentity, LoginResponse


class FakeService:
    def __init__(self) -> None:
        self.settings = SimpleNamespace(kb_name="爱分享", kb_owner="购物小助手", kb_title="【爱分享】的财经资讯")
        self.ask_stream_should_fail = False

    def health(self) -> HealthResponse:
        return HealthResponse(
            ok=True,
            instance="default",
            source_driver="web",
            base_url="https://ima.qq.com/",
            profile_dir="profile",
            headless=True,
            managed_profile_dir="managed",
        )

    def login(self, timeout_seconds: float | None = None) -> LoginResponse:
        return LoginResponse(
            ok=True,
            instance="default",
            base_url="https://ima.qq.com/",
            profile_dir="profile",
            timeout_seconds=timeout_seconds or 180,
        )

    def ask(self, question: str) -> AskResponse:
        kb = KnowledgeBaseIdentity(name="爱分享", owner="购物小助手", title="【爱分享】的财经资讯")
        return AskResponse(ok=True, question=question, knowledge_base=kb, mode="对话模式", model="DS V3.2", answer_text="final")

    def ask_with_updates(self, question: str, on_update=None) -> AskResponse:
        if self.ask_stream_should_fail:
            raise RuntimeError("boom")
        kb = KnowledgeBaseIdentity(name="爱分享", owner="购物小助手", title="【爱分享】的财经资讯")
        if on_update is not None:
            on_update("片段", "完整片段")
        return AskResponse(
            ok=True,
            question=question,
            knowledge_base=kb,
            mode="对话模式",
            model="DS V3.2",
            answer_text="final",
            answer_html="<p>final</p>",
        )


@contextmanager
def running_server(service: FakeService):
    server = create_chat_ui_server(service=service, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def request_json(url: str, method: str = "GET", payload: dict | None = None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        request.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(request, timeout=5) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def test_chat_ui_serves_index_and_assets():
    service = FakeService()
    with running_server(service) as base_url:
        with urllib.request.urlopen(f"{base_url}/", timeout=5) as response:
            index_html = response.read().decode("utf-8")
        with urllib.request.urlopen(f"{base_url}/assets/app.js", timeout=5) as response:
            app_js = response.read().decode("utf-8")

    assert "/assets/app.css" in index_html
    assert "爱分享 / 购物小助手 / 【爱分享】的财经资讯" in index_html
    assert "answer_html" in app_js


def test_chat_ui_health_login_and_stream_success():
    service = FakeService()
    with running_server(service) as base_url:
        status, health = request_json(f"{base_url}/api/health")
        assert status == 200
        assert health["ok"] is True

        status, login = request_json(f"{base_url}/api/login", method="POST", payload={"timeout": 12})
        assert status == 200
        assert login["ok"] is True
        assert login["timeout_seconds"] == 12.0

        request = urllib.request.Request(
            f"{base_url}/api/ask-stream",
            data=json.dumps({"question": "你好"}).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            events = [json.loads(line) for line in response.read().decode("utf-8").splitlines() if line.strip()]

    assert [event["type"] for event in events] == ["start", "delta", "done"]
    assert events[-1]["response"]["answer_html"] == "<p>final</p>"


def test_chat_ui_stream_failure_and_empty_question():
    service = FakeService()
    service.ask_stream_should_fail = True
    with running_server(service) as base_url:
        try:
            request_json(f"{base_url}/api/ask-stream", method="POST", payload={"question": "   "})
        except urllib.error.HTTPError as exc:
            assert exc.code == 400
            payload = json.loads(exc.read().decode("utf-8"))
            assert payload["error_code"] == "ASK_TIMEOUT"

        request = urllib.request.Request(
            f"{base_url}/api/ask-stream",
            data=json.dumps({"question": "你好"}).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            events = [json.loads(line) for line in response.read().decode("utf-8").splitlines() if line.strip()]

    assert events[0]["type"] == "error" or events[-1]["type"] == "error" or any(event["type"] == "error" for event in events)
