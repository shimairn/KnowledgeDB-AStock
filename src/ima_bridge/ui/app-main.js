import { prepareAnswerRender } from "/assets/app-render.js";
import { createMessageRenderer } from "/assets/app-view.js";

const dom = {
  shell: document.getElementById("appShell"),
  kbLabel: document.getElementById("kbLabel"),
  statusWrap: document.getElementById("statusWrap"),
  statusDot: document.getElementById("statusDot"),
  statusText: document.getElementById("statusText"),
  heroDescription: document.getElementById("heroDescription"),
  emptyState: document.getElementById("emptyState"),
  conversationViewport: document.getElementById("conversationViewport"),
  chat: document.getElementById("chat"),
  jumpToLatestBtn: document.getElementById("jumpToLatestBtn"),
  composer: document.getElementById("composer"),
  question: document.getElementById("question"),
  sendBtn: document.getElementById("sendBtn"),
  newConversationBtn: document.getElementById("newConversationBtn"),
  modelMenu: document.getElementById("modelMenu"),
  modelMenuTrigger: document.getElementById("modelMenuTrigger"),
  modelMenuLabel: document.getElementById("modelMenuLabel"),
  modelMenuList: document.getElementById("modelMenuList"),
};

const DEFAULT_KB_LABEL = "正在连接知识库";
const DEFAULT_EMPTY_ANSWER = "未获取到可展示的富文本回答，请重试。";
const DEFAULT_HERO_DESCRIPTION = "围绕当前知识库直接提问，回答会以富文本连续呈现。";
const AUTO_CLEAR_MS = 10 * 60 * 1000;
const QUESTION_MIN_HEIGHT = 52;
const QUESTION_MAX_HEIGHT = 220;
const VIEWPORT_BOTTOM_THRESHOLD = 96;

const state = {
  isBusy: false,
  autoClearTimer: 0,
  modelOptions: [],
  modelMenuOpen: false,
  selectedModel: "",
  shouldAutoScroll: true,
  hasPendingConversationUpdate: false,
};

const renderer = createMessageRenderer({
  chat: dom.chat,
  noteActivity,
  scrollChatToBottom: () => handleConversationUpdate(),
  onMessageMount: handleMessageMount,
});

export async function bootstrap() {
  setKbLabel(DEFAULT_KB_LABEL);
  setStatus("ready", "初始化中...");
  setHeroDescription(DEFAULT_HERO_DESCRIPTION);
  clearConversation({ focus: false });
  syncQuestionHeight();
  syncUiState();
  noteActivity();

  void loadUiConfig().catch(() => {
    setKbLabel(DEFAULT_KB_LABEL);
    renderModelMenu();
  });
  void refreshHealth();
  window.setInterval(refreshHealth, 15000);
  dom.question.focus();
}

function historyMessageCount() {
  return dom.chat.querySelectorAll(".msg").length;
}

function syncUiState() {
  syncEmptyState();
  syncQuestionHeight();
  syncComposerState();
  syncJumpToLatestButton();
}

function syncEmptyState() {
  dom.emptyState.hidden = historyMessageCount() > 0;
}

function isViewportNearBottom() {
  const { scrollHeight, scrollTop, clientHeight } = dom.conversationViewport;
  return scrollHeight - scrollTop - clientHeight <= VIEWPORT_BOTTOM_THRESHOLD;
}

function setAutoScrollEnabled(enabled) {
  state.shouldAutoScroll = Boolean(enabled);
  if (state.shouldAutoScroll) {
    state.hasPendingConversationUpdate = false;
  }
  syncJumpToLatestButton();
}

function syncJumpToLatestButton() {
  const visible = state.hasPendingConversationUpdate && !state.shouldAutoScroll;
  dom.jumpToLatestBtn.hidden = !visible;
  dom.jumpToLatestBtn.classList.toggle("is-visible", visible);
}

function scrollChatToBottom(options = {}) {
  const { force = false, smooth = false } = options;
  if (!force && !state.shouldAutoScroll) {
    state.hasPendingConversationUpdate = true;
    syncJumpToLatestButton();
    return;
  }

  dom.conversationViewport.scrollTo({
    top: dom.conversationViewport.scrollHeight,
    behavior: smooth ? "smooth" : "auto",
  });
  setAutoScrollEnabled(true);
}

function handleConversationUpdate(options = {}) {
  const { force = false } = options;
  if (force || state.shouldAutoScroll || isViewportNearBottom()) {
    scrollChatToBottom({ force: true });
    return;
  }
  state.hasPendingConversationUpdate = true;
  syncJumpToLatestButton();
}

function handleMessageMount() {
  syncUiState();
  handleConversationUpdate({ force: true });
}

function syncComposerState() {
  const hasQuestion = Boolean(dom.question.value.trim());
  const hasHistory = historyMessageCount() > 0;

  dom.sendBtn.disabled = state.isBusy || !hasQuestion;
  dom.newConversationBtn.disabled = state.isBusy || !hasHistory;
  dom.newConversationBtn.hidden = !hasHistory;

  const hasModels = state.modelOptions.length > 0;
  dom.modelMenu.hidden = !hasModels;
  dom.modelMenu.classList.toggle("is-disabled", state.isBusy || state.modelOptions.length <= 1);
  if (!hasModels || state.isBusy || state.modelOptions.length <= 1) {
    setModelMenuOpen(false);
  }
}

function syncQuestionHeight() {
  dom.question.style.height = "auto";
  const nextHeight = Math.max(QUESTION_MIN_HEIGHT, Math.min(QUESTION_MAX_HEIGHT, dom.question.scrollHeight || 0));
  dom.question.style.height = `${nextHeight}px`;
  dom.question.style.overflowY = (dom.question.scrollHeight || 0) > QUESTION_MAX_HEIGHT ? "auto" : "hidden";
}

function setBusy(value) {
  state.isBusy = Boolean(value);
  syncComposerState();
}

function setHeroDescription(text) {
  dom.heroDescription.textContent = String(text || "").trim() || DEFAULT_HERO_DESCRIPTION;
}

function scheduleAutoClear() {
  if (state.autoClearTimer) {
    window.clearTimeout(state.autoClearTimer);
  }
  state.autoClearTimer = window.setTimeout(() => {
    if (state.isBusy) {
      scheduleAutoClear();
      return;
    }
    if (historyMessageCount() > 0 || dom.question.value.trim()) {
      clearConversation({ focus: false });
    }
    scheduleAutoClear();
  }, AUTO_CLEAR_MS);
}

function noteActivity() {
  scheduleAutoClear();
}

function setKbLabel(label) {
  const normalized = String(label || "").trim() || DEFAULT_KB_LABEL;
  dom.kbLabel.textContent = normalized;
  document.title = `${normalized} - 匿名问答`;
}

function setStatus(kind, text) {
  dom.statusWrap.className = `status status--${kind}`;
  dom.statusDot.className = `status-dot status-dot--${kind}`;
  dom.statusText.textContent = text;
}

function setHealthStatus(payload) {
  if (payload?.ok) {
    setStatus("ready", "已连接");
    return;
  }
  if (payload?.error_code === "BUSY") {
    setStatus("busy", "服务繁忙");
    return;
  }
  if (payload?.error_code === "LOGIN_REQUIRED") {
    setStatus("error", "需要登录");
    return;
  }
  if (payload?.error_code === "KB_NOT_FOUND") {
    setStatus("error", "知识库未确认");
    return;
  }
  setStatus("error", "连接异常");
}

function findModelOption(value) {
  return state.modelOptions.find((option) => option.value === value || option.label === value) || null;
}

function renderModelMenu() {
  updateModelMenuLabel();
  dom.modelMenuList.innerHTML = "";

  state.modelOptions.forEach((option) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "model-menu__option";
    if (option.value === state.selectedModel) {
      button.classList.add("is-selected");
    }

    const copy = document.createElement("span");
    copy.className = "model-menu__option-copy";

    const title = document.createElement("span");
    title.className = "model-menu__option-title";
    title.textContent = option.label;
    copy.appendChild(title);

    if (option.description) {
      const meta = document.createElement("span");
      meta.className = "model-menu__option-meta";
      meta.textContent = option.description;
      copy.appendChild(meta);
    }

    button.appendChild(copy);

    if (option.value === state.selectedModel) {
      const check = document.createElement("span");
      check.className = "model-menu__option-check";
      check.textContent = "当前";
      button.appendChild(check);
    }

    button.addEventListener("click", async () => {
      if (state.isBusy) {
        return;
      }
      state.selectedModel = option.value;
      renderModelMenu();
      await ensureModelMenuClosed();
      syncComposerState();
      noteActivity();
      dom.question.focus();
    });

    dom.modelMenuList.appendChild(button);
  });
}

function updateModelMenuLabel() {
  const current = findModelOption(state.selectedModel);
  dom.modelMenuLabel.textContent = current?.label || "选择模型";
}

function applyModelCatalog(payload = {}) {
  state.modelOptions = Array.isArray(payload.model_options)
    ? payload.model_options
        .map((option) => ({
          value: String(option?.value || option?.label || "").trim(),
          label: String(option?.label || option?.value || "").trim(),
          description: String(option?.description || "").trim(),
          selected: Boolean(option?.selected),
        }))
        .filter((option) => option.value && option.label)
    : [];

  if (!state.modelOptions.length) {
    state.selectedModel = "";
    renderModelMenu();
    syncComposerState();
    return;
  }

  const currentModel = String(payload.current_model || "").trim();
  const selectedOption =
    findModelOption(currentModel) ||
    state.modelOptions.find((option) => option.selected) ||
    state.modelOptions[0] ||
    null;

  state.selectedModel = selectedOption?.value || "";
  renderModelMenu();
  syncComposerState();
}

function waitForFrames(count = 2) {
  return new Promise((resolve) => {
    const step = (remaining) => {
      if (remaining <= 0) {
        resolve();
        return;
      }
      requestAnimationFrame(() => step(remaining - 1));
    };
    step(count);
  });
}

function setModelMenuOpen(open) {
  const nextOpen = Boolean(open) && !dom.modelMenu.hidden && !dom.modelMenu.classList.contains("is-disabled");
  state.modelMenuOpen = nextOpen;
  dom.modelMenu.classList.toggle("is-open", nextOpen);
  dom.modelMenuTrigger.setAttribute("aria-expanded", String(nextOpen));
  dom.modelMenuList.hidden = !nextOpen;
}

async function ensureModelMenuClosed() {
  if (dom.modelMenu.hidden || !state.modelMenuOpen) {
    return;
  }
  setModelMenuOpen(false);
  await waitForFrames(2);
}

function clearConversation(options = {}) {
  const { focus = true } = options;
  state.hasPendingConversationUpdate = false;
  dom.chat.innerHTML = "";
  dom.question.value = "";
  dom.conversationViewport.scrollTop = 0;
  setAutoScrollEnabled(true);
  syncUiState();
  if (focus) {
    dom.question.focus();
  }
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
  if (code === "RATE_LIMITED") {
    return "请求过于频繁，请稍后重试";
  }
  const message = payload?.error_message || "请求失败";
  return `${code}: ${message}`;
}

function renderAssistantResponse(view, payload, fallbackAnswerHtml, fallbackThinkingText) {
  const prepared = prepareAnswerRender(payload?.answer_html || fallbackAnswerHtml || "");
  if (prepared.contentHtml) {
    view.setMainHtml(prepared.contentHtml);
  } else {
    view.setErrorText(DEFAULT_EMPTY_ANSWER);
  }

  const thinkingText = String(payload?.thinking_text || fallbackThinkingText || "").trim();
  view.finalizeThinking(thinkingText);
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

  setKbLabel(data.kb_label);
  applyModelCatalog(data);
  return data;
}

async function refreshHealth() {
  try {
    const { resp, data } = await fetchJson("/api/health");
    if (!resp.ok || !data) {
      throw new Error("读取健康状态失败");
    }
    setHealthStatus(data);
    return data;
  } catch (_) {
    setHealthStatus({ ok: false });
    return null;
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

async function askQuestion(question) {
  noteActivity();
  renderer.appendUserMessage(question);

  const assistantView = renderer.createAssistantView();
  assistantView.showPlaceholder();
  assistantView.setStreamingState("thinking");
  assistantView.row.classList.add("is-streaming");
  setBusy(true);
  setStatus("busy", "正在生成回答");

  let donePayload = null;
  let streamAnswerHtml = "";
  let streamThinkingText = "";
  const payload = { question };
  if (state.selectedModel) {
    payload.model = state.selectedModel;
  }

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
      noteActivity();

      if (event.type === "thinking_delta") {
        streamThinkingText = typeof event.text === "string" ? event.text : `${streamThinkingText}${event.delta || ""}`;
        assistantView.setStreamingState(streamAnswerHtml ? "answer" : "thinking");
        assistantView.queueThinkingText(streamThinkingText, { streaming: true });
        return;
      }

      if (event.type === "answer_html") {
        const prepared = prepareAnswerRender(event.html || "");
        if (!prepared.contentHtml) {
          return;
        }
        streamAnswerHtml = prepared.contentHtml;
        assistantView.setStreamingState("answer");
        assistantView.queueMainHtml(streamAnswerHtml);
        return;
      }

      if (event.type === "error") {
        throw new Error(formatApiError(event));
      }

      if (event.type === "done") {
        donePayload = event.response || null;
      }
    });

    assistantView.row.classList.remove("is-streaming");
    assistantView.clearStreamingState();

    if (!donePayload) {
      throw new Error("STREAM_ENDED_WITHOUT_DONE");
    }

    if (donePayload.ok) {
      renderAssistantResponse(assistantView, donePayload, streamAnswerHtml, streamThinkingText);
      await refreshHealth();
      return;
    }

    throw new Error(formatApiError(donePayload));
  } catch (error) {
    assistantView.row.classList.remove("is-streaming");
    assistantView.clearStreamingState();
    assistantView.setErrorText(error instanceof Error ? error.message : String(error));
    assistantView.finalizeThinking(streamThinkingText);
    setStatus("error", "请求失败");
  } finally {
    setBusy(false);
  }
}

async function submitComposerQuestion() {
  const question = dom.question.value.trim();
  if (!question || state.isBusy) {
    return;
  }
  await ensureModelMenuClosed();
  dom.question.value = "";
  syncUiState();
  await askQuestion(question);
}

dom.composer.addEventListener("submit", async (event) => {
  event.preventDefault();
  await submitComposerQuestion();
});

dom.question.addEventListener("keydown", async (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    await submitComposerQuestion();
  }
});

dom.question.addEventListener("input", () => {
  syncUiState();
  noteActivity();
});

dom.conversationViewport.addEventListener(
  "scroll",
  () => {
    setAutoScrollEnabled(isViewportNearBottom());
    noteActivity();
  },
  { passive: true },
);

dom.jumpToLatestBtn.addEventListener("click", () => {
  scrollChatToBottom({ force: true, smooth: true });
  noteActivity();
});

dom.newConversationBtn.addEventListener("click", async () => {
  await ensureModelMenuClosed();
  clearConversation();
  noteActivity();
});

dom.modelMenuTrigger.addEventListener("click", (event) => {
  if (state.isBusy || state.modelOptions.length <= 1) {
    event.preventDefault();
    return;
  }
  setModelMenuOpen(!state.modelMenuOpen);
  noteActivity();
});

document.addEventListener("click", (event) => {
  const target = event.target;
  if (state.modelMenuOpen && target instanceof Node && !dom.modelMenu.contains(target)) {
    void ensureModelMenuClosed();
  }
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    void ensureModelMenuClosed();
  }
});

window.addEventListener("pageshow", (event) => {
  if (event.persisted) {
    clearConversation({ focus: false });
  }
  noteActivity();
});
