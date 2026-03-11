const HTML_BASE_URL = "https://ima.qq.com/";
const DEFAULT_STARTUP_POLL_INTERVAL_MS = 1500;
const DEFAULT_STEADY_POLL_INTERVAL_MS = 15000;
const QUESTION_MIN_HEIGHT = 52;
const QUESTION_MAX_HEIGHT = 220;

const dom = {
  kbLabel: document.getElementById("kbLabel"),
  statusWrap: document.getElementById("statusWrap"),
  statusDot: document.getElementById("statusDot"),
  statusText: document.getElementById("statusText"),
  emptyState: document.getElementById("emptyState"),
  conversationViewport: document.getElementById("conversationViewport"),
  chat: document.getElementById("chat"),
  composer: document.getElementById("composer"),
  question: document.getElementById("question"),
  sendBtn: document.getElementById("sendBtn"),
  newConversationBtn: document.getElementById("newConversationBtn"),
  modelMenu: document.getElementById("modelMenu"),
  modelMenuList: document.getElementById("modelMenuList"),
};

const state = {
  isBusy: false,
  healthPollTimer: 0,
  startupPollIntervalMs: DEFAULT_STARTUP_POLL_INTERVAL_MS,
  steadyPollIntervalMs: DEFAULT_STEADY_POLL_INTERVAL_MS,
  modelOptions: [],
  selectedModel: "",
  lastHealth: null,
};

export async function bootstrap() {
  setKbLabel("知识库");
  setStatus("ready", "初始化中...");
  clearConversation({ focus: false });
  syncQuestionHeight();
  syncUiState();

  bindEvents();

  try {
    const config = await loadUiConfig();
    applyHealthPayload(config.health || null);
    scheduleHealthRefresh(getHealthRefreshDelay(config.health || null));
  } catch (_) {
    await refreshHealth();
  }

  dom.question?.focus();
}

function bindEvents() {
  if (dom.composer) {
    dom.composer.addEventListener("submit", async (event) => {
      event.preventDefault();
      await submitComposerQuestion();
    });
  }

  if (dom.question) {
    dom.question.addEventListener("keydown", async (event) => {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        await submitComposerQuestion();
      }
    });

    dom.question.addEventListener("input", () => {
      syncQuestionHeight();
      syncUiState();
    });
  }

  if (dom.newConversationBtn) {
    dom.newConversationBtn.addEventListener("click", () => {
      if (state.isBusy) {
        return;
      }
      clearConversation();
    });
  }

  if (dom.modelMenuList) {
    dom.modelMenuList.addEventListener("change", () => {
      const value = String(dom.modelMenuList.value || "").trim();
      state.selectedModel = value;
      syncUiState();
      dom.question?.focus();
    });
  }
}

function setKbLabel(value) {
  const text = String(value || "").trim() || "知识库";
  if (dom.kbLabel) {
    dom.kbLabel.textContent = text;
  }
  document.title = text;
}

function setStatus(kind, text) {
  if (!dom.statusWrap || !dom.statusDot || !dom.statusText) {
    return;
  }
  dom.statusWrap.className = `status status--${kind}`;
  dom.statusDot.className = `status-dot status-dot--${kind}`;
  dom.statusText.textContent = String(text || "").trim();
}

function setBusy(value) {
  state.isBusy = Boolean(value);
  syncUiState();
}

function historyMessageCount() {
  return dom.chat ? dom.chat.querySelectorAll(".msg").length : 0;
}

function syncEmptyState() {
  if (!dom.emptyState) {
    return;
  }
  dom.emptyState.hidden = historyMessageCount() > 0;
}

function syncComposerState() {
  const question = String(dom.question?.value || "");
  const hasQuestion = Boolean(question.trim());
  const hasHistory = historyMessageCount() > 0;

  if (dom.sendBtn) {
    dom.sendBtn.disabled = state.isBusy || !hasQuestion;
  }

  if (dom.newConversationBtn) {
    dom.newConversationBtn.hidden = !hasHistory;
    dom.newConversationBtn.disabled = state.isBusy || !hasHistory;
  }

  if (dom.modelMenu) {
    dom.modelMenu.hidden = state.modelOptions.length <= 1;
  }

  if (dom.modelMenuList) {
    dom.modelMenuList.disabled = state.isBusy || state.modelOptions.length <= 1;
  }
}

function syncUiState() {
  syncEmptyState();
  syncComposerState();
}

function syncQuestionHeight() {
  if (!dom.question) {
    return;
  }
  dom.question.style.height = "auto";
  const nextHeight = Math.max(
    QUESTION_MIN_HEIGHT,
    Math.min(QUESTION_MAX_HEIGHT, dom.question.scrollHeight || 0),
  );
  dom.question.style.height = `${nextHeight}px`;
}

function scrollChatToBottom() {
  if (!dom.conversationViewport) {
    return;
  }
  dom.conversationViewport.scrollTo({
    top: dom.conversationViewport.scrollHeight,
    behavior: "auto",
  });
}

function clearConversation(options = {}) {
  const { focus = true } = options;
  if (dom.chat) {
    dom.chat.innerHTML = "";
  }
  if (dom.question) {
    dom.question.value = "";
  }
  if (dom.conversationViewport) {
    dom.conversationViewport.scrollTop = 0;
  }
  syncQuestionHeight();
  syncUiState();
  if (focus) {
    dom.question?.focus();
  }
}

function appendUserMessage(text) {
  if (!dom.chat) {
    return;
  }
  const row = document.createElement("article");
  row.className = "msg user";

  const bubble = document.createElement("div");
  bubble.className = "bubble bubble--user";

  const body = document.createElement("div");
  body.className = "bubble__text";
  body.textContent = String(text || "");

  bubble.appendChild(body);
  row.appendChild(bubble);
  dom.chat.appendChild(row);
}

function createAssistantMessage({ placeholder = "" } = {}) {
  if (!dom.chat) {
    return { row: null, body: null };
  }

  const row = document.createElement("article");
  row.className = "msg assistant";

  const bubble = document.createElement("div");
  bubble.className = "bubble bubble--assistant";

  const body = document.createElement("div");
  body.className = "rich-content";
  if (placeholder) {
    body.className = "bubble__placeholder";
    body.textContent = placeholder;
  }

  bubble.appendChild(body);
  row.appendChild(bubble);
  dom.chat.appendChild(row);
  return { row, body };
}

function setAssistantHtml(host, html) {
  if (!host) {
    return;
  }
  host.className = "rich-content";
  host.innerHTML = sanitizeHtml(String(html || ""));
}

function setAssistantText(host, text) {
  if (!host) {
    return;
  }
  host.className = "bubble__text";
  host.textContent = String(text || "");
}

function sanitizeHtml(rawHtml) {
  const source = String(rawHtml || "").trim();
  if (!source) {
    return "";
  }

  const parser = new DOMParser();
  const documentHtml = /<html[\s>]/i.test(source)
    ? source
    : `<!doctype html><html><head></head><body>${source}</body></html>`;
  const doc = parser.parseFromString(documentHtml, "text/html");

  doc.querySelectorAll("script,noscript,style,link,meta,base,iframe,object,embed,form,input,textarea,button,select,option,svg,canvas").forEach((node) => node.remove());

  Array.from(doc.querySelectorAll("*")).forEach((el) => {
    Array.from(el.attributes).forEach((attr) => {
      const name = attr.name.toLowerCase();
      const value = String(attr.value || "");
      if (name.startsWith("on")) {
        el.removeAttribute(attr.name);
        return;
      }
      if (name === "href" || name === "src") {
        if (/^(?:javascript|vbscript|data):/i.test(value.trim())) {
          el.removeAttribute(attr.name);
        }
      }
    });
  });

  doc.querySelectorAll("a[href]").forEach((a) => {
    const href = a.getAttribute("href") || "";
    try {
      a.setAttribute("href", new URL(href, HTML_BASE_URL).href);
      a.setAttribute("target", "_blank");
      a.setAttribute("rel", "noreferrer");
    } catch (_) {
      a.removeAttribute("href");
    }
  });

  doc.querySelectorAll("img[src]").forEach((img) => {
    const src = img.getAttribute("src") || "";
    try {
      img.setAttribute("src", new URL(src, HTML_BASE_URL).href);
      img.setAttribute("loading", "lazy");
    } catch (_) {
      img.removeAttribute("src");
    }
    if (!img.getAttribute("alt")) {
      img.setAttribute("alt", "");
    }
  });

  return (doc.body?.innerHTML || "").trim();
}

async function submitComposerQuestion() {
  const question = String(dom.question?.value || "").trim();
  if (!question || state.isBusy) {
    return;
  }

  dom.question.value = "";
  syncQuestionHeight();
  syncUiState();
  await askQuestion(question);
}

async function askQuestion(question) {
  appendUserMessage(question);
  const view = createAssistantMessage({ placeholder: "正在生成回答..." });
  syncUiState();
  scrollChatToBottom();

  setBusy(true);
  setStatus("busy", "生成中...");

  const payload = { question };
  if (state.selectedModel) {
    payload.model = state.selectedModel;
  }

  let streamAnswerHtml = "";
  let streamThinkingText = "";
  let donePayload = null;

  try {
    const resp = await fetch("/api/ask-stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (!resp.ok) {
      let errorPayload = null;
      try {
        errorPayload = await resp.json();
      } catch (_) {
        errorPayload = { error_code: "REQUEST_FAILED", error_message: `HTTP ${resp.status}` };
      }
      throw new Error(formatApiError(errorPayload));
    }

    await readJsonLines(resp, (event) => {
      if (event.type === "thinking_delta") {
        streamThinkingText = typeof event.text === "string" ? event.text : `${streamThinkingText}${event.delta || ""}`;
        // Do not display thinking; only reflect activity in status.
        setStatus("busy", streamAnswerHtml ? "生成中..." : "整理中...");
        return;
      }

      if (event.type === "answer_html") {
        const html = String(event.html || "").trim();
        if (!html) {
          return;
        }
        streamAnswerHtml = html;
        setAssistantHtml(view.body, streamAnswerHtml);
        scrollChatToBottom();
        return;
      }

      if (event.type === "error") {
        throw new Error(formatApiError(event));
      }

      if (event.type === "done") {
        donePayload = event.response || null;
      }
    });

    if (!donePayload) {
      throw new Error("STREAM_ENDED_WITHOUT_DONE");
    }

    if (donePayload.ok) {
      const finalHtml = String(donePayload.answer_html || streamAnswerHtml || "").trim();
      if (finalHtml) {
        setAssistantHtml(view.body, finalHtml);
      } else {
        setAssistantText(view.body, String(donePayload.answer_text || "未获取到可展示的回答。"));
      }
      state.lastHealth = null;
      await refreshHealth();
      return;
    }

    throw new Error(formatApiError(donePayload));
  } catch (error) {
    setStatus("error", "请求失败");
    const message = error instanceof Error ? error.message : String(error || "请求失败");
    setAssistantText(view.body, message);
    return;
  } finally {
    setBusy(false);
    syncUiState();
    scrollChatToBottom();
  }
}

async function readJsonLines(response, onLine) {
  if (!response.body) {
    throw new Error("STREAM_NOT_SUPPORTED");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) {
      break;
    }

    buffer += decoder.decode(value, { stream: true });
    let newlineIndex = buffer.indexOf("\n");
    while (newlineIndex !== -1) {
      const line = buffer.slice(0, newlineIndex).trim();
      buffer = buffer.slice(newlineIndex + 1);
      if (line) {
        onLine(JSON.parse(line));
      }
      newlineIndex = buffer.indexOf("\n");
    }
  }

  const tail = buffer.trim();
  if (tail) {
    onLine(JSON.parse(tail));
  }
}

function setPollingConfig(payload = {}) {
  const startup = Number(payload.startup_poll_interval_ms);
  const steady = Number(payload.steady_poll_interval_ms);
  state.startupPollIntervalMs =
    Number.isFinite(startup) && startup > 0 ? startup : DEFAULT_STARTUP_POLL_INTERVAL_MS;
  state.steadyPollIntervalMs =
    Number.isFinite(steady) && steady > 0 ? steady : DEFAULT_STEADY_POLL_INTERVAL_MS;
}

function scheduleHealthRefresh(delay = state.startupPollIntervalMs) {
  if (state.healthPollTimer) {
    window.clearTimeout(state.healthPollTimer);
  }
  state.healthPollTimer = window.setTimeout(() => {
    void refreshHealth();
  }, Math.max(250, Number(delay) || state.startupPollIntervalMs));
}

function getHealthRefreshDelay(payload) {
  return payload?.ok ? state.steadyPollIntervalMs : state.startupPollIntervalMs;
}

async function fetchJson(url, options = undefined) {
  const resp = await fetch(url, options);
  const contentType = resp.headers.get("content-type") || "";
  let data = null;
  if (contentType.includes("application/json")) {
    data = await resp.json();
  }
  return { resp, data };
}

async function loadUiConfig() {
  const { resp, data } = await fetchJson("/api/ui-config");
  if (!resp.ok || !data) {
    throw new Error("读取界面配置失败");
  }

  setPollingConfig(data);
  setKbLabel(String(data.kb_label || "").trim() || "知识库");
  applyModelCatalog(data);
  return data;
}

async function refreshHealth() {
  let nextPayload = null;
  try {
    const { resp, data } = await fetchJson("/api/health");
    if (!resp.ok || !data) {
      throw new Error("读取健康状态失败");
    }
    nextPayload = data;
    applyHealthPayload(data);
    return data;
  } catch (_) {
    nextPayload = { ok: false, status: "error", error_code: "REQUEST_FAILED", error_message: "health failed" };
    applyHealthPayload(nextPayload);
    return null;
  } finally {
    scheduleHealthRefresh(getHealthRefreshDelay(nextPayload));
  }
}

function applyHealthPayload(payload) {
  state.lastHealth = payload;
  setHealthStatus(payload);
}

function setHealthStatus(payload) {
  if (payload?.ok) {
    setStatus("ready", "已连接");
    return;
  }
  if (payload?.error_code === "BUSY" || payload?.status === "busy") {
    setStatus("busy", "服务繁忙");
    return;
  }
  if (payload?.error_code === "WARMING_UP" || payload?.status === "warming") {
    setStatus("busy", "初始化中...");
    return;
  }
  if (payload?.error_code === "LOGIN_REQUIRED") {
    setStatus("error", "需要重新登录");
    return;
  }
  if (payload?.error_code === "KB_NOT_FOUND") {
    setStatus("error", "知识库未确认");
    return;
  }
  setStatus("error", "连接异常");
}

function applyModelCatalog(payload = {}) {
  const options = Array.isArray(payload.model_options)
    ? payload.model_options
        .map((option) => ({
          value: String(option?.value || option?.label || "").trim(),
          label: String(option?.label || option?.value || "").trim(),
          selected: Boolean(option?.selected),
        }))
        .filter((option) => option.value && option.label)
    : [];

  state.modelOptions = options;

  if (!dom.modelMenuList) {
    return;
  }

  dom.modelMenuList.innerHTML = "";

  if (!options.length) {
    state.selectedModel = "";
    syncUiState();
    return;
  }

  const currentModel = String(payload.current_model || "").trim();
  const selectedOption =
    options.find((opt) => opt.value === currentModel || opt.label === currentModel) ||
    options.find((opt) => opt.selected) ||
    options[0];

  state.selectedModel = selectedOption?.value || "";

  options.forEach((opt) => {
    const item = document.createElement("option");
    item.value = opt.value;
    item.textContent = opt.label;
    dom.modelMenuList.appendChild(item);
  });

  dom.modelMenuList.value = state.selectedModel;
  syncUiState();
}

function formatApiError(payload) {
  const code = payload?.error_code || "REQUEST_FAILED";
  if (code === "LOGIN_REQUIRED") {
    return "请先完成登录后再使用问答服务";
  }
  if (code === "KB_NOT_FOUND") {
    return "请先登录并进入目标知识库后再提问";
  }
  if (code === "BUSY") {
    return "服务繁忙，请稍后重试";
  }
  if (code === "WARMING_UP") {
    return "服务仍在初始化，请稍后重试";
  }
  if (code === "RATE_LIMITED") {
    return "请求过于频繁，请稍后重试";
  }
  const message = payload?.error_message || "请求失败";
  return `${code}: ${message}`;
}

