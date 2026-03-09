import { prepareAnswerRender } from "/assets/app-render.js";
import { createMessageRenderer } from "/assets/app-view.js";

const dom = {
  shell: document.getElementById("appShell"),
  kbLabel: document.getElementById("kbLabel"),
  statusWrap: document.getElementById("statusWrap"),
  statusDot: document.getElementById("statusDot"),
  statusText: document.getElementById("statusText"),
  heroDescription: document.getElementById("heroDescription"),
  startupPanel: document.getElementById("startupPanel"),
  startupPhase: document.getElementById("startupPhase"),
  startupCount: document.getElementById("startupCount"),
  startupBar: document.getElementById("startupBar"),
  startupHint: document.getElementById("startupHint"),
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
  composerHint: document.getElementById("composerHint"),
  promptCards: Array.from(document.querySelectorAll(".prompt-card")),
};

const DISPLAY_KB_LABEL = "财经知识库";
const DISPLAY_DOCUMENT_TITLE = "财经知识库";
const DEFAULT_KB_LABEL = DISPLAY_KB_LABEL;
const DEFAULT_EMPTY_ANSWER = "未获取到可展示的富文本回答，请重试。";
const DEFAULT_HERO_DESCRIPTION = "围绕市场、公司或政策直接提问，系统会把答案整理成清晰的富文本结构，方便快速阅读与继续追问。";
const DEFAULT_COMPOSER_HINT = "点击上方示例问题，或直接输入你的问题";
const ACTIVE_COMPOSER_HINT = "Enter 发送，Shift+Enter 换行";
const BUSY_COMPOSER_HINT = "正在生成富文本回答，请稍候";
const AUTO_CLEAR_MS = 10 * 60 * 1000;
const QUESTION_MIN_HEIGHT = 52;
const QUESTION_MAX_HEIGHT = 220;
const VIEWPORT_BOTTOM_THRESHOLD = 96;
const DEFAULT_STARTUP_POLL_INTERVAL_MS = 1500;
const DEFAULT_STEADY_POLL_INTERVAL_MS = 15000;
const STARTUP_HERO_DESCRIPTION = "\u670d\u52a1\u6b63\u5728\u521d\u59cb\u5316\uff0c\u9996\u4e2a worker \u5c31\u7eea\u540e\u5373\u53ef\u5f00\u59cb\u63d0\u95ee\u3002";
const LOGIN_REQUIRED_HERO_DESCRIPTION = "\u5f53\u524d worker \u767b\u5f55\u6001\u5931\u6548\uff0c\u9700\u8981\u7ba1\u7406\u5458\u91cd\u65b0\u767b\u5f55\u540e\u624d\u80fd\u7ee7\u7eed\u4f7f\u7528\u3002";
const ERROR_HERO_DESCRIPTION = "\u6b63\u5728\u5c1d\u8bd5\u91cd\u65b0\u8fde\u63a5\u77e5\u8bc6\u5e93\uff0c\u8bf7\u7a0d\u540e\u518d\u8bd5\u3002";
const BUSY_HERO_DESCRIPTION = "\u5f53\u524d\u6709\u95ee\u9898\u6b63\u5728\u5904\u7406\uff0c\u7a0d\u540e\u5c31\u4f1a\u91ca\u653e worker \u5bb9\u91cf\u3002";

const state = {
  isBusy: false,
  autoClearTimer: 0,
  healthPollTimer: 0,
  modelOptions: [],
  modelMenuOpen: false,
  selectedModel: "",
  shouldAutoScroll: true,
  hasPendingConversationUpdate: false,
  startupPollIntervalMs: DEFAULT_STARTUP_POLL_INTERVAL_MS,
  steadyPollIntervalMs: DEFAULT_STEADY_POLL_INTERVAL_MS,
  lastHealth: null,
};

const renderer = createMessageRenderer({
  chat: dom.chat,
  noteActivity,
  scrollChatToBottom: () => handleConversationUpdate(),
  onMessageMount: handleMessageMount,
  setComposerDraft: fillSuggestedQuestion,
});

export async function bootstrap() {
  setKbLabel();
  setStatus("ready", "初始化中...");
  setHeroDescription(STARTUP_HERO_DESCRIPTION);
  clearConversation({ focus: false });
  syncQuestionHeight();
  syncUiState();
  noteActivity();

  try {
    const config = await loadUiConfig();
    applyHealthPayload(config.health || null);
    scheduleHealthRefresh(getHealthRefreshDelay(config.health || null));
  } catch (_) {
    setKbLabel();
    renderModelMenu();
    await refreshHealth();
  }
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
  syncStartupPanel(state.lastHealth);
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
  dom.composer.classList.toggle("is-busy", state.isBusy);

  const hasModels = state.modelOptions.length > 0;
  dom.modelMenu.hidden = !hasModels;
  dom.modelMenu.classList.toggle("is-disabled", state.isBusy || state.modelOptions.length <= 1);
  if (!hasModels || state.isBusy || state.modelOptions.length <= 1) {
    setModelMenuOpen(false);
  }

  syncComposerHint();
}

function syncQuestionHeight() {
  dom.question.style.height = "auto";
  const nextHeight = Math.max(QUESTION_MIN_HEIGHT, Math.min(QUESTION_MAX_HEIGHT, dom.question.scrollHeight || 0));
  dom.question.style.height = `${nextHeight}px`;
  dom.question.style.overflowY = (dom.question.scrollHeight || 0) > QUESTION_MAX_HEIGHT ? "auto" : "hidden";
}

function syncComposerHint() {
  if (!dom.composerHint) {
    return;
  }

  const hasHistory = historyMessageCount() > 0;
  const hasQuestion = Boolean(dom.question.value.trim());
  const currentModel = findModelOption(state.selectedModel);

  if (state.isBusy) {
    dom.composerHint.textContent = BUSY_COMPOSER_HINT;
    return;
  }

  if (hasQuestion) {
    dom.composerHint.textContent = ACTIVE_COMPOSER_HINT;
    return;
  }

  if (!hasHistory) {
    dom.composerHint.textContent = currentModel
      ? `${currentModel.label} 已就绪 · ${DEFAULT_COMPOSER_HINT}`
      : DEFAULT_COMPOSER_HINT;
    return;
  }

  dom.composerHint.textContent = currentModel
    ? `${currentModel.label} 已就绪 · 可继续追问或新建对话`
    : "可继续追问，或新建对话开始新的主题";
}

function setBusy(value) {
  state.isBusy = Boolean(value);
  syncComposerState();
}

function setHeroDescription(text) {
  dom.heroDescription.textContent = String(text || "").trim() || DEFAULT_HERO_DESCRIPTION;
}

function setPollingConfig(payload = {}) {
  const startup = Number(payload.startup_poll_interval_ms);
  const steady = Number(payload.steady_poll_interval_ms);
  state.startupPollIntervalMs = Number.isFinite(startup) && startup > 0 ? startup : DEFAULT_STARTUP_POLL_INTERVAL_MS;
  state.steadyPollIntervalMs = Number.isFinite(steady) && steady > 0 ? steady : DEFAULT_STEADY_POLL_INTERVAL_MS;
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

function getPoolSummary(payload = {}) {
  const pool = payload?.pool || {};
  return {
    total: Number(pool.workers_total || 0),
    warming: Number(pool.workers_warming || 0),
    ready: Number(pool.workers_ready || 0),
    busy: Number(pool.workers_busy || 0),
    loginRequired: Number(pool.workers_login_required || 0),
    error: Number(pool.workers_error || 0),
  };
}

function setStartupPanelState(kind, phase, count, hint, progress) {
  dom.startupPanel.hidden = false;
  dom.startupPanel.dataset.state = kind;
  dom.startupPhase.textContent = phase;
  dom.startupCount.textContent = count;
  dom.startupHint.textContent = hint;
  dom.startupBar.style.width = `${Math.max(0, Math.min(100, progress))}%`;
}

function syncStartupPanel(payload) {
  const summary = getPoolSummary(payload || state.lastHealth || {});
  if (!summary.total) {
    dom.startupPanel.hidden = true;
    return;
  }

  const kind = String(payload?.status || (payload?.ok ? "ready" : "error"));
  const countText = `${summary.ready}/${summary.total}`;
  const activeCount = Math.max(summary.ready, summary.ready + summary.busy);
  const baseProgress = summary.total > 0 ? Math.round((activeCount / summary.total) * 100) : 0;
  const warmingProgress = kind === "warming" && baseProgress === 0 ? 12 : baseProgress;

  if (kind === "ready") {
    const hint = payload?.warming_up
      ? `\u5df2\u5c31\u7eea ${countText}\uff0c\u5176\u4f59 worker \u6b63\u5728\u9884\u70ed\uff0c\u53ef\u76f4\u63a5\u5f00\u59cb\u63d0\u95ee\u3002`
      : "\u5df2\u8fde\u63a5\u5230\u77e5\u8bc6\u5e93\uff0c\u53ef\u76f4\u63a5\u5f00\u59cb\u63d0\u95ee\u3002";
    setStartupPanelState("ready", "\u670d\u52a1\u5df2\u5c31\u7eea", countText, hint, payload?.warming_up ? Math.max(24, warmingProgress) : 100);
    return;
  }

  if (kind === "warming") {
    setStartupPanelState(
      "warming",
      "\u670d\u52a1\u542f\u52a8\u4e2d",
      countText,
      "\u6b63\u5728\u9884\u70ed\u6d4f\u89c8\u5668 worker\uff0c\u9996\u4e2a worker \u5c31\u7eea\u540e\u5373\u53ef\u5f00\u59cb\u63d0\u95ee\u3002",
      warmingProgress,
    );
    return;
  }

  if (kind === "busy") {
    setStartupPanelState(
      "busy",
      "\u670d\u52a1\u7e41\u5fd9",
      countText,
      "\u5f53\u524d\u53ef\u7528 worker \u5df2\u7ecf\u88ab\u5360\u7528\uff0c\u7a0d\u540e\u4f1a\u91ca\u653e\u5bb9\u91cf\u3002",
      Math.max(24, baseProgress || 100),
    );
    return;
  }

  if (kind === "login_required") {
    setStartupPanelState(
      "login_required",
      "\u9700\u8981\u91cd\u65b0\u767b\u5f55",
      countText,
      "\u5f53\u524d worker \u767b\u5f55\u6001\u5931\u6548\uff0c\u9700\u8981\u7ba1\u7406\u5458\u91cd\u65b0\u767b\u5f55\u540e\u624d\u80fd\u6062\u590d\u3002",
      baseProgress,
    );
    return;
  }

  setStartupPanelState(
    "error",
    "\u8fde\u63a5\u5f02\u5e38",
    countText,
    "\u6b63\u5728\u5c1d\u8bd5\u91cd\u65b0\u8fde\u63a5\u77e5\u8bc6\u5e93\uff0c\u8bf7\u7a0d\u540e\u91cd\u8bd5\u3002",
    baseProgress,
  );
}

function applyHealthPayload(payload) {
  state.lastHealth = payload;
  setHealthStatus(payload);
  syncStartupPanel(payload);
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

function setKbLabel() {
  dom.kbLabel.textContent = DISPLAY_KB_LABEL;
  document.title = DISPLAY_DOCUMENT_TITLE;
}

function setStatus(kind, text) {
  dom.statusWrap.className = `status status--${kind}`;
  dom.statusDot.className = `status-dot status-dot--${kind}`;
  dom.statusText.textContent = text;
}

function setHealthStatus(payload) {
  const summary = getPoolSummary(payload);
  const readyCount = summary.total > 0 ? `${summary.ready}/${summary.total}` : "";

  if (payload?.ok) {
    setStatus(
      "ready",
      payload?.warming_up && readyCount ? `已连接·${readyCount} 就绪` : "已连接",
    );
    setHeroDescription(payload?.warming_up ? STARTUP_HERO_DESCRIPTION : DEFAULT_HERO_DESCRIPTION);
    return;
  }
  if (payload?.status === "warming" || payload?.error_code === "WARMING_UP") {
    setStatus("busy", readyCount ? `正在初始化 ${readyCount}` : "正在初始化");
    setHeroDescription(STARTUP_HERO_DESCRIPTION);
    return;
  }
  if (payload?.error_code === "BUSY") {
    setStatus("busy", "服务繁忙");
    setHeroDescription(BUSY_HERO_DESCRIPTION);
    return;
  }
  if (payload?.error_code === "LOGIN_REQUIRED") {
    setStatus("error", "需要重新登录");
    setHeroDescription(LOGIN_REQUIRED_HERO_DESCRIPTION);
    return;
  }
  if (payload?.error_code === "KB_NOT_FOUND") {
    setStatus("error", "知识库未确认");
    setHeroDescription(ERROR_HERO_DESCRIPTION);
    return;
  }
  setStatus("error", "连接异常");
  setHeroDescription(ERROR_HERO_DESCRIPTION);
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

async function fillSuggestedQuestion(question) {
  const normalized = String(question || "").trim();
  if (!normalized || state.isBusy) {
    return;
  }

  await ensureModelMenuClosed();
  dom.question.value = normalized;
  syncUiState();
  noteActivity();

  if (window.matchMedia("(max-width: 920px)").matches) {
    dom.composer.scrollIntoView({ block: "end", behavior: "smooth" });
  }

  dom.question.focus();
  const cursor = dom.question.value.length;
  dom.question.setSelectionRange(cursor, cursor);
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
    return "服务仍在初始化，请稍候片刻再试";
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

  setPollingConfig(data);
  setKbLabel();
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
    nextPayload = { ok: false, status: "error", pool: state.lastHealth?.pool || null };
    applyHealthPayload(nextPayload);
    return null;
  } finally {
    scheduleHealthRefresh(getHealthRefreshDelay(nextPayload));
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

dom.promptCards.forEach((button) => {
  button.addEventListener("click", async () => {
    await fillSuggestedQuestion(button.dataset.question || button.textContent || "");
  });
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
