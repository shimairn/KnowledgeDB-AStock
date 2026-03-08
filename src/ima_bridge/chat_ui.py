from __future__ import annotations

import html
import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from typing import Callable

from ima_bridge.service import IMAAskService


def _load_asset(name: str) -> str:
    return files("ima_bridge.ui").joinpath(name).read_text(encoding="utf-8")


class ChatUIServer(ThreadingHTTPServer):
    def __init__(self, server_address: tuple[str, int], service: IMAAskService) -> None:
        super().__init__(server_address, ChatUIRequestHandler)
        self.service = service
        self.lock = threading.Lock()
        self.assets = {
            "index.html": _load_asset("index.html"),
            "app.css": _load_asset("app.css"),
            "app.js": _load_asset("app.js"),
        }

    def render_index(self) -> str:
        kb_label = html.escape(
            f"{self.service.settings.kb_name} / {self.service.settings.kb_owner} / {self.service.settings.kb_title}"
        )
        return self.assets["index.html"].replace("__KB_LABEL__", kb_label)

    def run_json(self, fn: Callable[[], dict]) -> dict:
        with self.lock:
            return fn()

    def run_stream(self, question: str, writer: Callable[[dict], None]) -> None:
        with self.lock:
            writer({"type": "start", "question": question})

            def on_update(delta: str, text: str) -> None:
                if not delta:
                    return
                writer({"type": "delta", "delta": delta, "text": text})

            response = self.service.ask_with_updates(question=question, on_update=on_update)
            writer({"type": "done", "response": response.model_dump()})


class ChatUIRequestHandler(BaseHTTPRequestHandler):
    server: ChatUIServer

    def do_GET(self) -> None:
        if self.path == "/":
            self._send_text(self.server.render_index(), content_type="text/html; charset=utf-8")
            return
        if self.path == "/assets/app.css":
            self._send_text(self.server.assets["app.css"], content_type="text/css; charset=utf-8")
            return
        if self.path == "/assets/app.js":
            self._send_text(self.server.assets["app.js"], content_type="application/javascript; charset=utf-8")
            return
        if self.path == "/api/health":
            self._run_json(lambda: self.server.service.health().model_dump())
            return
        self._send_json({"ok": False, "error": "NOT_FOUND"}, status=404)

    def do_POST(self) -> None:
        if self.path == "/api/ask":
            body = self._read_json()
            question = str(body.get("question", "")).strip()
            if not question:
                self._send_json(
                    {"ok": False, "error_code": "ASK_TIMEOUT", "error_message": "question is required"},
                    status=400,
                )
                return
            self._run_json(lambda: self.server.service.ask(question).model_dump())
            return
        if self.path == "/api/ask-stream":
            body = self._read_json()
            question = str(body.get("question", "")).strip()
            if not question:
                self._send_json(
                    {"ok": False, "error_code": "ASK_TIMEOUT", "error_message": "question is required"},
                    status=400,
                )
                return
            self._run_stream(question)
            return
        if self.path == "/api/login":
            body = self._read_json()
            timeout = body.get("timeout")
            timeout_value = float(timeout) if timeout is not None else None
            self._run_json(lambda: self.server.service.login(timeout_seconds=timeout_value).model_dump())
            return
        self._send_json({"ok": False, "error": "NOT_FOUND"}, status=404)

    def log_message(self, format: str, *args) -> None:
        return

    def _run_json(self, fn: Callable[[], dict]) -> None:
        try:
            payload = self.server.run_json(fn)
            self._send_json(payload)
        except Exception as exc:
            self._send_json(
                {
                    "ok": False,
                    "error_code": "CAPTURE_FAILED",
                    "error_message": str(exc),
                },
                status=500,
            )

    def _run_stream(self, question: str) -> None:
        try:
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.server.run_stream(question, self._write_stream)
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception as exc:
            try:
                self._write_stream(
                    {
                        "type": "error",
                        "error_code": "CAPTURE_FAILED",
                        "error_message": str(exc),
                    }
                )
            except Exception:
                return

    def _read_json(self) -> dict:
        content_length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(content_length) if content_length > 0 else b"{}"
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return {}

    def _write_stream(self, payload: dict) -> None:
        encoded = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
        self.wfile.write(encoded)
        self.wfile.flush()

    def _send_text(self, value: str, content_type: str, status: int = 200) -> None:
        encoded = value.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(encoded)

    def _send_json(self, payload: dict, status: int = 200) -> None:
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(encoded)


def create_chat_ui_server(service: IMAAskService, host: str, port: int) -> ChatUIServer:
    return ChatUIServer((host, port), service)


def run_chat_ui(
    service: IMAAskService,
    host: str,
    port: int,
    open_browser: bool,
) -> int:
    server = create_chat_ui_server(service=service, host=host, port=port)
    url = f"http://{host}:{server.server_address[1]}/"
    print(f"ui running: {url}")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
