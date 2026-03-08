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
