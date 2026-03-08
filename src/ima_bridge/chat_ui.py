from __future__ import annotations

import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable

from ima_bridge.service import IMAAskService

INDEX_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>ima 对话</title>
  <style>
    :root {
      --bg: #f4f6fb;
      --card: #fff;
      --line: #e3e8f5;
      --text: #1e2a45;
      --sub: #67718f;
      --primary: #2f5cf3;
      --ok: #1a9d5c;
      --err: #dd3b4a;
    }
    * { box-sizing: border-box; }
    html, body { height: 100%; margin: 0; }
    body {
      background: linear-gradient(150deg, #0d1837 0%, #172852 45%, #203465 100%);
      font-family: "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
      color: var(--text);
      padding: 14px;
    }
    .app {
      height: calc(100vh - 28px);
      max-width: 1080px;
      margin: 0 auto;
      background: var(--bg);
      border-radius: 16px;
      border: 1px solid rgba(255,255,255,.18);
      overflow: hidden;
      display: grid;
      grid-template-rows: auto 1fr auto;
      box-shadow: 0 18px 42px rgba(8, 16, 40, .35);
    }
    .top {
      background: #fff;
      border-bottom: 1px solid var(--line);
      padding: 10px 14px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
    }
    .title {
      display: flex;
      flex-direction: column;
      gap: 2px;
    }
    .title b { font-size: 16px; }
    .title span { font-size: 12px; color: var(--sub); }
    .actions { display: flex; gap: 8px; align-items: center; }
    .badge {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 6px 10px;
      border-radius: 999px;
      border: 1px solid #d6def8;
      background: #eff3ff;
      color: #304275;
      font-size: 12px;
      font-weight: 600;
    }
    .dot { width: 8px; height: 8px; border-radius: 50%; background: #9aa5c9; }
    .dot.ok { background: var(--ok); }
    .dot.err { background: var(--err); }
    button {
      border: 1px solid var(--line);
      background: #fff;
      color: var(--text);
      border-radius: 8px;
      padding: 7px 11px;
      cursor: pointer;
      font-size: 13px;
    }
    button.primary {
      background: var(--primary);
      color: #fff;
      border-color: var(--primary);
    }
    button:disabled { opacity: .55; cursor: not-allowed; }
    .chat {
      overflow: auto;
      padding: 14px;
      display: flex;
      flex-direction: column;
      gap: 12px;
    }
    .msg {
      max-width: 92%;
      display: flex;
      gap: 8px;
      align-items: flex-end;
    }
    .msg.user {
      margin-left: auto;
      flex-direction: row-reverse;
    }
    .avatar {
      width: 28px;
      height: 28px;
      border-radius: 50%;
      display: grid;
      place-items: center;
      font-size: 11px;
      font-weight: 700;
      color: #fff;
      flex: 0 0 auto;
    }
    .avatar.user { background: #4a67f4; }
    .avatar.ai { background: #1ea6c8; }
    .bubble {
      border: 1px solid var(--line);
      background: var(--card);
      border-radius: 12px;
      padding: 10px 12px;
      white-space: pre-wrap;
      line-height: 1.5;
      font-size: 14px;
      box-shadow: 0 4px 14px rgba(20, 40, 90, .06);
    }
    .msg.user .bubble {
      background: #e8efff;
      border-color: #c7d5ff;
    }
    .bubble.streaming::after {
      content: "▋";
      display: inline-block;
      margin-left: 2px;
      color: #5574f3;
      animation: caretBlink 1s steps(1) infinite;
    }
    @keyframes caretBlink {
      0%, 50% { opacity: 1; }
      51%, 100% { opacity: 0; }
    }
    .html-wrap {
      margin-top: 8px;
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
      background: #fff;
    }
    .html-wrap iframe {
      width: 100%;
      border: 0;
      display: block;
      min-height: 160px;
    }
    .composer {
      border-top: 1px solid var(--line);
      padding: 10px;
      background: #fff;
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 10px;
    }
    textarea {
      width: 100%;
      min-height: 78px;
      max-height: 220px;
      resize: vertical;
      border: 1px solid #d6def5;
      border-radius: 10px;
      padding: 10px;
      font: inherit;
      line-height: 1.45;
      outline: none;
      background: #fcfdff;
    }
    .send {
      align-self: end;
      height: 42px;
      padding: 0 16px;
      border-radius: 10px;
      border: 1px solid var(--primary);
      background: var(--primary);
      color: #fff;
      font-weight: 600;
    }
  </style>
</head>
<body>
  <div class="app">
    <div class="top">
      <div class="title">
        <b>ima 官方 AI 对话</b>
        <span>固定知识库：爱分享 / 购物小助手 / 【爱分享】的财经资讯</span>
      </div>
      <div class="actions">
        <div class="badge"><span id="statusDot" class="dot"></span><span id="statusText">检测中...</span></div>
        <button id="loginBtn">登录</button>
        <button id="clearBtn">清空</button>
      </div>
    </div>

    <div class="chat" id="chat"></div>

    <form class="composer" id="form">
      <textarea id="question" placeholder="输入问题，Enter 发送，Shift+Enter 换行"></textarea>
      <button class="send" id="sendBtn" type="submit">发送</button>
    </form>
  </div>

  <script>
    const chat = document.getElementById("chat");
    const form = document.getElementById("form");
    const questionEl = document.getElementById("question");
    const sendBtn = document.getElementById("sendBtn");
    const loginBtn = document.getElementById("loginBtn");
    const clearBtn = document.getElementById("clearBtn");
    const statusDot = document.getElementById("statusDot");
    const statusText = document.getElementById("statusText");

    function setBusy(value) {
      sendBtn.disabled = value;
      loginBtn.disabled = value;
    }

    function setStatus(ok, text) {
      statusText.textContent = text;
      statusDot.className = "dot " + (ok ? "ok" : "err");
    }

    function pushMessage(role, text) {
      const row = document.createElement("div");
      row.className = `msg ${role}`;

      const avatar = document.createElement("div");
      avatar.className = `avatar ${role === "user" ? "user" : "ai"}`;
      avatar.textContent = role === "user" ? "你" : "AI";
      row.appendChild(avatar);

      const bubble = document.createElement("div");
      bubble.className = "bubble";
      bubble.textContent = text || "";
      row.appendChild(bubble);

      chat.appendChild(row);
      chat.scrollTop = chat.scrollHeight;
      return bubble;
    }

    function pushStreamingMessage() {
      const bubble = pushMessage("assistant", "正在请求 ima...");
      bubble.classList.add("streaming");
      return bubble;
    }

    function updateStreamingMessage(bubble, text) {
      bubble.textContent = text || "正在请求 ima...";
      chat.scrollTop = chat.scrollHeight;
    }

    function finishStreamingMessage(bubble) {
      bubble.classList.remove("streaming");
    }

    function wrapAnswerHtml(answerHtml) {
      const html = (answerHtml || "").trim();
      if (!html) {
        return `<!doctype html><html><head><meta charset="utf-8" /></head><body></body></html>`;
      }
      if (/<html[\s>]/i.test(html)) {
        return html;
      }
      return `<!doctype html><html><head><meta charset="utf-8" />
      <base href="https://ima.qq.com/" />
      <style>
        body { margin:0; padding:10px; font: 14px/1.6 "Segoe UI","PingFang SC","Microsoft YaHei",sans-serif; color:#1e2a45; background:#fff; }
        table { border-collapse: collapse; width: 100%; margin: 8px 0; font-size: 13px; }
        th, td { border: 1px solid #d5ddf3; padding: 6px 8px; text-align: left; }
        th { background: #f4f7ff; }
        img, svg, canvas, video { max-width: 100%; height: auto; }
        pre { white-space: pre-wrap; word-break: break-word; }
      </style></head><body>${html}</body></html>`;
    }

    function appendRichHtml(bubble, answerHtml) {
      if (!answerHtml) return;
      const box = document.createElement("div");
      box.className = "html-wrap";
      const frame = document.createElement("iframe");
      frame.setAttribute("sandbox", "allow-same-origin");
      frame.srcdoc = wrapAnswerHtml(answerHtml);

      const resizeFrame = () => {
        try {
          const doc = frame.contentDocument;
          if (!doc || !doc.body) return;
          const bodyHeight = doc.body.scrollHeight || 0;
          const docHeight = doc.documentElement ? doc.documentElement.scrollHeight || 0 : 0;
          const height = Math.max(160, Math.min(3200, Math.max(bodyHeight, docHeight) + 14));
          frame.style.height = `${height}px`;
        } catch (_) {}
      };

      frame.addEventListener("load", () => {
        resizeFrame();
        setTimeout(resizeFrame, 120);
        setTimeout(resizeFrame, 400);
        setTimeout(resizeFrame, 1200);
      });
      box.appendChild(frame);
      bubble.appendChild(box);
    }

    async function refreshHealth() {
      try {
        const resp = await fetch("/api/health");
        const data = await resp.json();
        if (data.ok) {
          setStatus(true, "已就绪");
        } else {
          setStatus(false, data.error_code || "不可用");
        }
      } catch (_) {
        setStatus(false, "连接失败");
      }
    }

    async function doLogin() {
      setBusy(true);
      try {
        const resp = await fetch("/api/login", { method: "POST" });
        const data = await resp.json();
        if (data.ok) {
          setStatus(true, "登录完成");
          pushMessage("assistant", "登录成功，可以继续提问。");
        } else {
          setStatus(false, data.error_code || "登录失败");
          pushMessage("assistant", `${data.error_code || "LOGIN_FAILED"}: ${data.error_message || "请先完成扫码登录"}`);
        }
      } finally {
        setBusy(false);
      }
      await refreshHealth();
    }

    async function readJsonLines(resp, onLine) {
      if (!resp.body) {
        throw new Error("流式响应不可用");
      }
      const reader = resp.body.getReader();
      const decoder = new TextDecoder("utf-8");
      let buffer = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        let newline = buffer.indexOf("\n");
        while (newline !== -1) {
          const line = buffer.slice(0, newline).trim();
          buffer = buffer.slice(newline + 1);
          if (line) {
            const data = JSON.parse(line);
            onLine(data);
          }
          newline = buffer.indexOf("\n");
        }
      }

      const tail = buffer.trim();
      if (tail) {
        const data = JSON.parse(tail);
        onLine(data);
      }
    }

    async function askQuestion(question) {
      pushMessage("user", question);
      const bubble = pushStreamingMessage();
      setBusy(true);

      let donePayload = null;
      let streamText = "";
      try {
        const resp = await fetch("/api/ask-stream", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({ question }),
        });
        if (!resp.ok) {
          throw new Error(`HTTP_${resp.status}`);
        }

        await readJsonLines(resp, (event) => {
          if (!event || typeof event !== "object") return;

          if (event.type === "delta") {
            if (typeof event.text === "string") {
              streamText = event.text;
            } else if (typeof event.delta === "string") {
              streamText += event.delta;
            }
            updateStreamingMessage(bubble, streamText);
            return;
          }

          if (event.type === "error") {
            const code = event.error_code || "STREAM_ERROR";
            const message = event.error_message || "stream failed";
            throw new Error(`${code}: ${message}`);
          }

          if (event.type === "done") {
            donePayload = event.response || null;
          }
        });

        finishStreamingMessage(bubble);
        if (!donePayload) {
          throw new Error("STREAM_ENDED_WITHOUT_DONE");
        }

        if (donePayload.ok) {
          const finalText = donePayload.answer_text || streamText || "(空回答)";
          bubble.textContent = finalText;
          if (donePayload.answer_html) {
            appendRichHtml(bubble, donePayload.answer_html);
          }
          setStatus(true, "回答完成");
        } else {
          bubble.textContent = `${donePayload.error_code || "ERROR"}: ${donePayload.error_message || "请求失败"}`;
          setStatus(false, donePayload.error_code || "请求失败");
        }
      } catch (error) {
        finishStreamingMessage(bubble);
        bubble.textContent = `REQUEST_ERROR: ${error}`;
        setStatus(false, "请求失败");
      } finally {
        setBusy(false);
      }
    }

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const question = questionEl.value.trim();
      if (!question) return;
      questionEl.value = "";
      await askQuestion(question);
    });

    questionEl.addEventListener("keydown", async (event) => {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        const question = questionEl.value.trim();
        if (!question) return;
        questionEl.value = "";
        await askQuestion(question);
      }
    });

    loginBtn.addEventListener("click", doLogin);
    clearBtn.addEventListener("click", () => {
      chat.innerHTML = "";
      pushMessage("assistant", "已清空对话。");
    });

    pushMessage("assistant", "已连接桥接器。你可以直接提问。");
    refreshHealth();
    setInterval(refreshHealth, 25000);
  </script>
</body>
</html>
"""


def run_chat_ui(
    service: IMAAskService,
    host: str,
    port: int,
    open_browser: bool,
) -> int:
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/":
                self._send_html(INDEX_HTML)
                return
            if self.path == "/api/health":
                self._run_json(lambda: service.health().model_dump())
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
                self._run_json(lambda: service.ask(question).model_dump())
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
                self._run_json(lambda: service.login(timeout_seconds=timeout_value).model_dump())
                return
            self._send_json({"ok": False, "error": "NOT_FOUND"}, status=404)

        def log_message(self, format: str, *args) -> None:
            return

        def _run_json(self, fn: Callable[[], dict]) -> None:
            try:
                with lock:
                    payload = fn()
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

                with lock:
                    self._write_stream({"type": "start", "question": question})

                    def on_update(delta: str, text: str) -> None:
                        if not delta:
                            return
                        self._write_stream({"type": "delta", "delta": delta, "text": text})

                    response = service.ask_with_updates(question=question, on_update=on_update)
                    self._write_stream({"type": "done", "response": response.model_dump()})
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

        def _send_html(self, value: str, status: int = 200) -> None:
            encoded = value.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
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

    server = ThreadingHTTPServer((host, port), Handler)
    url = f"http://{host}:{port}/"
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

