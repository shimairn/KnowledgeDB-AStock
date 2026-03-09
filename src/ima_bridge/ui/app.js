const chat = document.getElementById("chat");
const questionEl = document.getElementById("question");
const composer = document.getElementById("composer");
const sendBtn = document.getElementById("sendBtn");
const clearBtn = document.getElementById("clearBtn");
const modelField = document.getElementById("modelField");
const modelSelect = document.getElementById("modelSelect");
const thinkingToggle = document.getElementById("thinkingToggle");
const statusDot = document.getElementById("statusDot");
const statusText = document.getElementById("statusText");
const questionMeta = document.getElementById("questionMeta");
const drawerBackdrop = document.getElementById("drawerBackdrop");
const sourceDrawer = document.getElementById("sourceDrawer");
const sourceDrawerTitle = document.getElementById("sourceDrawerTitle");
const sourceDrawerMeta = document.getElementById("sourceDrawerMeta");
const sourceDrawerStatus = document.getElementById("sourceDrawerStatus");
const sourceDrawerOpenLink = document.getElementById("sourceDrawerOpenLink");
const sourceDrawerFrame = document.getElementById("sourceDrawerFrame");
const drawerCloseBtn = document.getElementById("drawerCloseBtn");

const INTRO_MESSAGE = "已连接，可直接提问。每次提问都会自动开启新对话，页面空闲后会自动清理。";
const HTML_BASE_URL = "https://ima.qq.com/";
const HTML_PARSER = new DOMParser();
const AUTO_CLEAR_MS = 10 * 60 * 1000;
const QUESTION_MIN_HEIGHT = 44;
const QUESTION_MAX_HEIGHT = 136;
const CHAT_BOTTOM_THRESHOLD = 96;

const NOISE_TEXT_PATTERNS = [
  /^ima$/i,
  /^找到了.*知识库资料$/,
  /^已找到.*知识库资料$/,
  /^(?:回答|答复|最终回答|final answer|answer)$/i,
  /^(?:思考过程|思考中|推理过程|reasoning|thinking)$/i,
  /^(?:展开|收起)$/,
];
const CITATION_ONLY_PATTERN = /^\s*(?:\[\d+\]|\d+)\s*$/;
const BAD_CLASS_PATTERN = /(modeldesc|modelwrap|toolbar|header|knowledge|sourcecount|quoteindex|refindex|referenceindex|citation|actionbar|sender|avatar|footer)/i;
const REMOVABLE_TAGS = new Set([
  "script",
  "style",
  "link",
  "meta",
  "noscript",
  "iframe",
  "object",
  "embed",
  "form",
  "input",
  "button",
  "textarea",
  "select",
  "option",
  "audio",
]);
const ALLOWED_TAGS = new Set([
  "a",
  "b",
  "blockquote",
  "br",
  "code",
  "div",
  "em",
  "figcaption",
  "figure",
  "h1",
  "h2",
  "h3",
  "h4",
  "h5",
  "h6",
  "hr",
  "i",
  "img",
  "li",
  "ol",
  "p",
  "pre",
  "s",
  "section",
  "span",
  "strong",
  "sub",
  "sup",
  "table",
  "tbody",
  "td",
  "th",
  "thead",
  "tr",
  "u",
  "ul",
]);
const VOID_TAGS = new Set(["br", "hr", "img"]);
const ATTRIBUTE_ALLOWLIST = {
  a: new Set(["href", "title", "target", "rel"]),
  img: new Set(["src", "alt", "title", "width", "height"]),
  th: new Set(["colspan", "rowspan", "scope"]),
  td: new Set(["colspan", "rowspan"]),
  ol: new Set(["start"]),
};

let isBusy = false;
let lastDrawerTrigger = null;
let autoClearTimer = 0;
let selectedModel = "";
let modelOptions = [];
let shouldAutoScroll = true;
let showThinking = true;

function normalizeWhitespace(value) {
  return String(value || "").replace(/\s+/g, " ").trim();
}

function isChatNearBottom() {
  return chat.scrollHeight - chat.scrollTop - chat.clientHeight <= CHAT_BOTTOM_THRESHOLD;
}

function scrollChatToBottom(force = false) {
  if (!force && !shouldAutoScroll) {
    return;
  }
  requestAnimationFrame(() => {
    chat.scrollTop = chat.scrollHeight;
    if (force) {
      shouldAutoScroll = true;
    }
  });
}

function setThinkingVisibility(value) {
  showThinking = Boolean(value);
  document.body.classList.toggle("thinking-hidden", !showThinking);
  if (thinkingToggle) {
    thinkingToggle.checked = showThinking;
  }
}

function historyMessageCount() {
  return chat.querySelectorAll(".msg:not(.is-intro)").length;
}

function syncIntroState() {
  const intro = chat.querySelector(".msg.is-intro");
  if (intro) {
    intro.hidden = historyMessageCount() > 0;
  }
}

function syncComposerState() {
  questionMeta.textContent = `${questionEl.value.length} 字`;
  sendBtn.disabled = isBusy || !questionEl.value.trim();
  clearBtn.disabled = isBusy || (!questionEl.value.trim() && historyMessageCount() === 0);
  if (modelSelect) {
    modelSelect.disabled = isBusy || modelOptions.length <= 1;
  }
  syncIntroState();
}

function syncQuestionHeight() {
  questionEl.style.height = "auto";
  const nextHeight = Math.max(QUESTION_MIN_HEIGHT, Math.min(QUESTION_MAX_HEIGHT, questionEl.scrollHeight || 0));
  questionEl.style.height = `${nextHeight}px`;
  questionEl.style.overflowY = (questionEl.scrollHeight || 0) > QUESTION_MAX_HEIGHT ? "auto" : "hidden";
}

function setBusy(value) {
  isBusy = value;
  syncComposerState();
}

function scheduleAutoClear() {
  if (autoClearTimer) {
    window.clearTimeout(autoClearTimer);
  }
  autoClearTimer = window.setTimeout(() => {
    if (isBusy) {
      scheduleAutoClear();
      return;
    }
    if (historyMessageCount() > 0 || questionEl.value.trim()) {
      clearConversation({ focus: false });
    }
    scheduleAutoClear();
  }, AUTO_CLEAR_MS);
}

function noteActivity() {
  scheduleAutoClear();
}

function setStatus(kind, text) {
  statusDot.className = `dot ${kind}`;
  statusText.textContent = text;
}

function setHealthStatus(payload) {
  if (payload?.ok) {
    setStatus("ready", "可直接提问");
    return;
  }
  if (payload?.error_code === "BUSY") {
    setStatus("busy", "服务繁忙，请稍后重试");
    return;
  }
  if (payload?.error_code === "LOGIN_REQUIRED") {
    setStatus("error", "需要先登录");
    return;
  }
  if (payload?.error_code === "KB_NOT_FOUND") {
    setStatus("error", "需要先确认知识库");
    return;
  }
  setStatus("error", "服务连接异常");
}

function findModelOption(value) {
  return modelOptions.find((option) => option.value === value || option.label === value) || null;
}

function applyModelCatalog(payload = {}) {
  modelOptions = Array.isArray(payload.model_options)
    ? payload.model_options
        .map((option) => ({
          value: String(option?.value || option?.label || "").trim(),
          label: String(option?.label || option?.value || "").trim(),
          description: String(option?.description || "").trim(),
          selected: Boolean(option?.selected),
        }))
        .filter((option) => option.value && option.label)
    : [];

  if (!modelField || !modelSelect) {
    return;
  }

  if (!modelOptions.length) {
    selectedModel = "";
    modelField.hidden = true;
    modelSelect.innerHTML = "";
    syncComposerState();
    return;
  }

  modelField.hidden = false;
  modelSelect.innerHTML = "";

  modelOptions.forEach((option) => {
    const item = document.createElement("option");
    item.value = option.value;
    item.textContent = option.label;
    if (option.description) {
      item.title = option.description;
    }
    modelSelect.appendChild(item);
  });

  const currentModel = String(payload.current_model || "").trim();
  const currentOption = findModelOption(currentModel);
  const selectedOption = currentOption || modelOptions.find((option) => option.selected) || modelOptions[0] || null;
  selectedModel = selectedOption?.value || "";
  if (selectedModel) {
    modelSelect.value = selectedModel;
  }
  syncComposerState();
}

function clearConversation(options = {}) {
  const { focus = true } = options;
  closeSourceDrawer({ restoreFocus: false });
  shouldAutoScroll = true;
  chat.innerHTML = "";
  questionEl.value = "";
  syncQuestionHeight();
  appendIntroMessage();
  syncComposerState();
  if (focus) {
    questionEl.focus();
  }
}function setDrawerVisibility(visible) {
  sourceDrawer.setAttribute("aria-hidden", String(!visible));
  document.body.classList.toggle("drawer-open", visible);

  if (visible) {
    sourceDrawer.hidden = false;
    drawerBackdrop.hidden = false;
    requestAnimationFrame(() => {
      sourceDrawer.classList.add("is-open");
      drawerBackdrop.classList.add("is-open");
    });
    return;
  }

  sourceDrawer.classList.remove("is-open");
  drawerBackdrop.classList.remove("is-open");
  setTimeout(() => {
    if (!sourceDrawer.classList.contains("is-open")) {
      sourceDrawer.hidden = true;
      drawerBackdrop.hidden = true;
    }
  }, 240);
}

function formatSourceHost(href) {
  try {
    const url = new URL(href);
    return `${url.hostname}${url.pathname}`;
  } catch (_) {
    return href;
  }
}

function closeSourceDrawer(options = {}) {
  const { restoreFocus = true } = options;
  if (sourceDrawer.hidden && !sourceDrawer.classList.contains("is-open")) {
    return;
  }

  setDrawerVisibility(false);
  sourceDrawerTitle.textContent = "原文预览";
  sourceDrawerMeta.textContent = "选择一条来源后，可在这里预览并跳转到原文。";
  sourceDrawerStatus.textContent = "部分站点可能禁止嵌入预览；如果未显示，可直接打开原文。";
  sourceDrawerOpenLink.href = "about:blank";
  sourceDrawerOpenLink.classList.add("is-disabled");
  sourceDrawerOpenLink.setAttribute("aria-disabled", "true");
  sourceDrawerOpenLink.tabIndex = -1;
  sourceDrawerFrame.src = "about:blank";

  if (restoreFocus && lastDrawerTrigger instanceof HTMLElement) {
    lastDrawerTrigger.focus();
  }
  lastDrawerTrigger = null;
}

function openSourceDrawer(source, trigger = null) {
  noteActivity();
  if (!source?.href) {
    return;
  }

  lastDrawerTrigger = trigger instanceof HTMLElement
    ? trigger
    : document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null;

  sourceDrawerTitle.textContent = source.title || "原文预览";
  sourceDrawerMeta.textContent = source.quote || formatSourceHost(source.href);
  sourceDrawerStatus.textContent = "正在加载原文预览；如果内容为空，可能是目标站点禁止嵌入。";
  sourceDrawerOpenLink.href = source.href;
  sourceDrawerOpenLink.classList.remove("is-disabled");
  sourceDrawerOpenLink.removeAttribute("aria-disabled");
  sourceDrawerOpenLink.tabIndex = 0;
  sourceDrawerFrame.src = source.href;
  setDrawerVisibility(true);
  setTimeout(() => drawerCloseBtn.focus(), 0);
}

function escapeHtml(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function textToRichHtml(value) {
  const source = String(value || "").replace(/\r\n?/g, "\n").trim();
  if (!source) {
    return "";
  }

  const lines = source.split("\n");
  const parts = [];
  let paragraph = [];
  let codeFence = false;
  let codeLines = [];

  const flushParagraph = () => {
    if (!paragraph.length) {
      return;
    }
    parts.push(`<p>${paragraph.map((line) => escapeHtml(line)).join("<br />")}</p>`);
    paragraph = [];
  };

  const flushCode = () => {
    if (!codeLines.length) {
      return;
    }
    parts.push(`<pre><code>${escapeHtml(codeLines.join("\n"))}</code></pre>`);
    codeLines = [];
  };

  for (const rawLine of lines) {
    const line = rawLine || "";
    if (line.trim().startsWith("```")) {
      flushParagraph();
      if (codeFence) {
        flushCode();
      }
      codeFence = !codeFence;
      continue;
    }

    if (codeFence) {
      codeLines.push(line);
      continue;
    }

    if (!line.trim()) {
      flushParagraph();
      continue;
    }

    paragraph.push(line);
  }

  flushParagraph();
  flushCode();
  return parts.join("");
}

function decorateRichAnchors(root) {
  root.querySelectorAll("a[href]").forEach((anchor) => {
    anchor.target = "_blank";
    anchor.rel = "noreferrer";
  });
}

function setRichContent(node, html) {
  node.innerHTML = html;
  decorateRichAnchors(node);
}

function renderTextRichContent(node, text, extraClass = "") {
  node.className = `bubble-text rich-content rich-content--text${extraClass ? ` ${extraClass}` : ""}`;
  setRichContent(node, textToRichHtml(text));
}

function commonPrefixLength(left, right) {
  const max = Math.min(left.length, right.length);
  let index = 0;
  while (index < max && left[index] === right[index]) {
    index += 1;
  }
  return index;
}

function createTypewriter(render) {
  let targetText = "";
  let renderedText = "";
  let frame = 0;

  function flush() {
    render(renderedText);
    scrollChatToBottom();
  }

  function step() {
    frame = 0;
    if (renderedText === targetText) {
      return;
    }

    const remaining = targetText.length - renderedText.length;
    const batch = remaining > 80 ? 3 : remaining > 20 ? 2 : 1;
    renderedText = targetText.slice(0, renderedText.length + batch);
    flush();

    if (renderedText !== targetText) {
      frame = requestAnimationFrame(step);
    }
  }

  return {
    queue(value) {
      const nextText = String(value || "");
      if (!nextText.startsWith(renderedText)) {
        const prefixLength = commonPrefixLength(nextText, renderedText);
        renderedText = nextText.slice(0, prefixLength);
        flush();
      }
      targetText = nextText;
      if (!frame) {
        frame = requestAnimationFrame(step);
      }
    },
    set(value) {
      if (frame) {
        cancelAnimationFrame(frame);
        frame = 0;
      }
      targetText = String(value || "");
      renderedText = targetText;
      flush();
    },
    stop() {
      if (frame) {
        cancelAnimationFrame(frame);
        frame = 0;
      }
    },
  };
}

function createMessageRow(role, extraClass = "") {
  const row = document.createElement("article");
  row.className = `msg ${role}${extraClass ? ` ${extraClass}` : ""}`;

  const avatar = document.createElement("div");
  avatar.className = `avatar ${role}`;
  avatar.textContent = role === "user" ? "你" : "AI";

  const bubble = document.createElement("div");
  bubble.className = "bubble";

  row.appendChild(avatar);
  row.appendChild(bubble);
  chat.appendChild(row);
  syncComposerState();
  scrollChatToBottom(true);

  return { row, bubble };
}

function appendUserMessage(text) {
  const { bubble } = createMessageRow("user");
  const body = document.createElement("div");
  body.className = "bubble-text";
  body.textContent = text || "";
  bubble.appendChild(body);
  return bubble;
}

function createDetailHeader(title, subtitle) {
  const header = document.createElement("div");
  header.className = "detail-header";

  const copy = document.createElement("div");
  const titleEl = document.createElement("h3");
  titleEl.className = "detail-title";
  titleEl.textContent = title;
  copy.appendChild(titleEl);

  if (subtitle) {
    const subtitleEl = document.createElement("p");
    subtitleEl.className = "detail-subtitle";
    subtitleEl.textContent = subtitle;
    copy.appendChild(subtitleEl);
  }

  header.appendChild(copy);
  return header;
}

function createSourceSection(items, references) {
  if (!items.length && !references.length) {
    return null;
  }

  const section = document.createElement("section");
  section.className = "detail-card";
  section.appendChild(createDetailHeader("引用原文", "在这里查看引用来源，也可以侧边预览或打开原文。"));

  if (items.length) {
    const grid = document.createElement("div");
    grid.className = "source-grid";

    items.forEach((item, index) => {
      const card = document.createElement("article");
      card.className = "source-card";

      const head = document.createElement("div");
      head.className = "source-card-head";
      const indexEl = document.createElement("span");
      indexEl.className = "source-index";
      indexEl.textContent = `来源 ${index + 1}`;
      head.appendChild(indexEl);
      card.appendChild(head);

      const title = document.createElement("p");
      title.className = "source-title";
      title.textContent = item.title;
      card.appendChild(title);

      if (item.quote) {
        const quote = document.createElement("blockquote");
        quote.className = "source-quote";
        quote.textContent = item.quote;
        card.appendChild(quote);
      }

      const footer = document.createElement("div");
      footer.className = "source-footer";

      const url = document.createElement("span");
      url.className = "source-url";
      url.textContent = item.href ? formatSourceHost(item.href) : "仅保留引用文本";
      footer.appendChild(url);

      if (item.href) {
        const actions = document.createElement("div");
        actions.className = "source-actions";

        const previewButton = document.createElement("button");
        previewButton.type = "button";
        previewButton.className = "source-link";
        previewButton.textContent = "侧边预览";
        previewButton.addEventListener("click", () => openSourceDrawer(item, previewButton));
        actions.appendChild(previewButton);

        const link = document.createElement("a");
        link.className = "source-link source-link--primary";
        link.href = item.href;
        link.target = "_blank";
        link.rel = "noreferrer";
        link.textContent = "打开原文";
        actions.appendChild(link);

        footer.appendChild(actions);
      }

      card.appendChild(footer);
      grid.appendChild(card);
    });

    section.appendChild(grid);
  }

  if (references.length) {
    const list = document.createElement("ol");
    list.className = "reference-list";
    references.forEach((reference) => {
      const item = document.createElement("li");
      item.textContent = stripReferenceMarker(reference) || reference;
      list.appendChild(item);
    });
    section.appendChild(list);
  }

  return section;
}

function createAssistantView({ intro = false } = {}) {
  const { row, bubble } = createMessageRow("assistant", intro ? "is-intro" : "");
  const main = document.createElement("div");
  main.className = "bubble-main";

  const body = document.createElement("div");
  body.className = "bubble-text rich-content rich-content--text";
  main.appendChild(body);

  const extras = document.createElement("div");
  extras.className = "bubble-extras";

  bubble.appendChild(main);
  bubble.appendChild(extras);

  let thinkingText = "";
  let thinkingDetails = null;
  let thinkingContent = null;
  let thinkingState = null;
  let thinkingCaption = null;
  let thinkingWriter = null;
  let sourceSection = null;
  const mainWriter = createTypewriter((value) => renderTextRichContent(body, value));

  function setMainText(value) {
    body.className = "bubble-text rich-content rich-content--text";
    mainWriter.set(String(value || ""));
  }

  function queueMainText(value) {
    body.className = "bubble-text rich-content rich-content--text";
    mainWriter.queue(String(value || ""));
  }

  function setMainHtml(value) {
    const normalized = String(value || "").trim();
    if (!normalized) {
      setMainText("");
      return;
    }
    mainWriter.stop();
    body.className = "bubble-text rich-content rich-content--answer";
    setRichContent(body, normalized);
    scrollChatToBottom();
  }

  function removeThinking() {
    if (thinkingWriter) {
      thinkingWriter.stop();
      thinkingWriter = null;
    }
    if (thinkingDetails) {
      thinkingDetails.remove();
      thinkingDetails = null;
      thinkingContent = null;
      thinkingState = null;
      thinkingCaption = null;
    }
    thinkingText = "";
  }

  function ensureThinking() {
    if (thinkingDetails) {
      return;
    }

    thinkingDetails = document.createElement("details");
    thinkingDetails.className = "thinking-card";

    const summary = document.createElement("summary");
    const copy = document.createElement("div");
    copy.className = "thinking-copy";

    const title = document.createElement("span");
    title.className = "thinking-title";
    title.textContent = "思考过程";

    thinkingCaption = document.createElement("span");
    thinkingCaption.className = "thinking-caption";
    thinkingCaption.textContent = "默认折叠，可随时展开查看。";

    thinkingState = document.createElement("span");
    thinkingState.className = "thinking-state";
    thinkingState.textContent = "思考中...";

    copy.appendChild(title);
    copy.appendChild(thinkingCaption);
    summary.appendChild(copy);
    summary.appendChild(thinkingState);

    const thinkingBody = document.createElement("div");
    thinkingBody.className = "thinking-body";

    thinkingContent = document.createElement("div");
    thinkingContent.className = "rich-content rich-content--thinking";
    thinkingBody.appendChild(thinkingContent);

    thinkingDetails.appendChild(summary);
    thinkingDetails.appendChild(thinkingBody);
    thinkingDetails.addEventListener("toggle", () => {
      noteActivity();
      scrollChatToBottom();
    });
    extras.appendChild(thinkingDetails);

    thinkingWriter = createTypewriter((value) => {
      if (thinkingContent) {
        setRichContent(thinkingContent, textToRichHtml(value));
      }
    });
  }

  function queueThinkingText(value, options = {}) {
    const { streaming = false } = options;
    const normalized = String(value || "").trim();
    if (!normalized) {
      if (!streaming) {
        removeThinking();
      }
      return;
    }

    ensureThinking();
    thinkingText = normalized;
    thinkingDetails.classList.toggle("is-live", Boolean(streaming));
    thinkingState.textContent = streaming ? "思考中..." : "已完成";
    thinkingCaption.textContent = streaming ? "生成中，可随时展开查看。" : "默认折叠，可随时展开查看。";
    thinkingWriter.queue(thinkingText);
  }

  function finalizeThinking(value) {
    const normalized = String(value || thinkingText || "").trim();
    if (!normalized) {
      removeThinking();
      return;
    }
    ensureThinking();
    thinkingText = normalized;
    thinkingDetails.classList.remove("is-live");
    thinkingState.textContent = "已完成";
    thinkingCaption.textContent = "默认折叠，可随时展开查看。";
    thinkingWriter.set(thinkingText);
  }

  function setSources(items, references = []) {
    if (sourceSection) {
      sourceSection.remove();
      sourceSection = null;
    }
    const next = createSourceSection(items, references);
    if (next) {
      sourceSection = next;
      extras.appendChild(sourceSection);
    }
  }

  return {
    row,
    queueMainText,
    setMainText,
    setMainHtml,
    queueThinkingText,
    finalizeThinking,
    setSources,
  };
}

function appendIntroMessage() {
  const view = createAssistantView({ intro: true });
  view.setMainText(INTRO_MESSAGE);
  return view;
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
  const message = payload?.error_message || "请求失败";
  return `${code}: ${message}`;
}

function stripReferenceMarker(value) {
  return String(value || "").replace(/^\[[^\]]+\]\s*/, "").trim();
}

function dedupeBy(values, keyFactory) {
  const results = [];
  const seen = new Set();
  for (const value of values) {
    const key = keyFactory(value);
    if (!key || seen.has(key)) {
      continue;
    }
    seen.add(key);
    results.push(value);
  }
  return results;
}

function extractReferenceLinesFromText(answerText) {
  return String(answerText || "")
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => /^\[[^\]]+\]\s+/.test(line));
}

function collectReferenceLines(payload) {
  const fromPayload = Array.isArray(payload?.references) ? payload.references : [];
  const fromText = extractReferenceLinesFromText(payload?.answer_text || "");
  return dedupeBy([...fromPayload, ...fromText].map((line) => String(line).trim()).filter(Boolean), (value) => value);
}

function stripReferenceLines(answerText) {
  const lines = String(answerText || "").split(/\r?\n/);
  const kept = lines.filter((line) => !/^\[[^\]]+\]\s+/.test(line.trim()));
  return kept.join("\n").trim();
}

function toHtmlDocument(answerHtml) {
  const rawHtml = String(answerHtml || "").trim();
  if (!rawHtml) {
    return HTML_PARSER.parseFromString("<!doctype html><html><body></body></html>", "text/html");
  }

  const documentHtml = /<html[\s>]/i.test(rawHtml)
    ? rawHtml
    : `<!doctype html><html><head><base href="${HTML_BASE_URL}" /></head><body>${rawHtml}</body></html>`;
  return HTML_PARSER.parseFromString(documentHtml, "text/html");
}

function resolveHtmlUrl(href) {
  try {
    return new URL(href, HTML_BASE_URL).href;
  } catch (_) {
    return String(href || "");
  }
}

function isNoiseText(text) {
  const normalized = normalizeWhitespace(text);
  return Boolean(normalized) && NOISE_TEXT_PATTERNS.some((pattern) => pattern.test(normalized));
}

function removeStructuralNoise(root, options = {}) {
  const { removeCitationOnly = true } = options;
  const removableSelector = Array.from(REMOVABLE_TAGS).join(",");
  if (removableSelector) {
    root.querySelectorAll(removableSelector).forEach((node) => node.remove());
  }
  root.querySelectorAll("[x-noteelement='excluded'], [data-noteelement='excluded']").forEach((node) => node.remove());

  const elements = Array.from(root.querySelectorAll("*")).reverse();
  elements.forEach((element) => {
    if (!element.isConnected) {
      return;
    }
    const tag = element.tagName.toLowerCase();
    const text = normalizeWhitespace(element.textContent);
    const className = String(element.getAttribute("class") || "");
    const attrText = normalizeWhitespace(`${className} ${element.id || ""} ${element.getAttribute("data-testid") || ""} ${element.getAttribute("data-role") || ""} ${element.getAttribute("aria-label") || ""}`);

    if (
      removeCitationOnly &&
      text &&
      CITATION_ONLY_PATTERN.test(text) &&
      ["sup", "a", "span", "button", "i", "em", "strong"].includes(tag)
    ) {
      element.remove();
      return;
    }

    if (
      text &&
      text.length <= 72 &&
      isNoiseText(text) &&
      !element.querySelector("table,blockquote,pre,img,code")
    ) {
      element.remove();
      return;
    }

    if (
      attrText &&
      BAD_CLASS_PATTERN.test(attrText) &&
      text.length <= 80 &&
      !element.querySelector("table,blockquote,pre,img,code")
    ) {
      element.remove();
    }
  });
}

function sanitizeElementAttributes(element) {
  const tag = element.tagName.toLowerCase();
  const allowed = ATTRIBUTE_ALLOWLIST[tag] || new Set();

  Array.from(element.attributes).forEach((attr) => {
    const name = attr.name.toLowerCase();
    if (
      name.startsWith("on") ||
      name.startsWith("data-") ||
      name.startsWith("aria-") ||
      name === "class" ||
      name === "style" ||
      name === "id" ||
      name === "role" ||
      name === "tabindex" ||
      name === "contenteditable" ||
      !allowed.has(name)
    ) {
      element.removeAttribute(attr.name);
    }
  });

  if (tag === "a") {
    const href = resolveHtmlUrl(element.getAttribute("href") || "");
    if (!/^https?:\/\//i.test(href)) {
      element.replaceWith(...Array.from(element.childNodes));
      return false;
    }
    element.setAttribute("href", href);
    element.setAttribute("target", "_blank");
    element.setAttribute("rel", "noreferrer");
    return true;
  }

  if (tag === "img") {
    const src = resolveHtmlUrl(element.getAttribute("src") || "");
    if (!/^https?:\/\//i.test(src)) {
      element.remove();
      return false;
    }
    element.setAttribute("src", src);
    if (!element.getAttribute("alt")) {
      element.setAttribute("alt", "");
    }
    return true;
  }

  return true;
}

function stripEmptyNodes(root) {
  const elements = Array.from(root.querySelectorAll("*")).reverse();
  elements.forEach((element) => {
    if (!element.isConnected) {
      return;
    }
    const tag = element.tagName.toLowerCase();
    if (VOID_TAGS.has(tag) || ["table", "thead", "tbody", "tr", "td", "th"].includes(tag)) {
      return;
    }
    if (element.querySelector("img,br,table,pre,blockquote,ul,ol")) {
      return;
    }
    if (!normalizeWhitespace(element.textContent)) {
      element.remove();
    }
  });
}

function sanitizeHtmlTree(root, options = {}) {
  removeStructuralNoise(root, options);

  const elements = Array.from(root.querySelectorAll("*")).reverse();
  elements.forEach((element) => {
    if (!element.isConnected) {
      return;
    }

    const tag = element.tagName.toLowerCase();
    if (REMOVABLE_TAGS.has(tag)) {
      element.remove();
      return;
    }

    if (!ALLOWED_TAGS.has(tag)) {
      element.replaceWith(...Array.from(element.childNodes));
      return;
    }

    sanitizeElementAttributes(element);
  });

  stripEmptyNodes(root);
}

function sanitizeAnswerHtml(answerHtml) {
  const doc = toHtmlDocument(answerHtml);
  sanitizeHtmlTree(doc.body, { removeCitationOnly: true });
  return doc.body.innerHTML.trim();
}

function extractHtmlArtifacts(answerHtml) {
  const doc = toHtmlDocument(answerHtml);
  sanitizeHtmlTree(doc.body, { removeCitationOnly: false });

  const links = dedupeBy(
    Array.from(doc.querySelectorAll("a[href]"))
      .map((anchor, index) => ({
        href: resolveHtmlUrl(anchor.getAttribute("href") || anchor.href || ""),
        label: normalizeWhitespace(anchor.textContent) || `原文 ${index + 1}`,
      }))
      .filter((item) => /^https?:\/\//i.test(item.href)),
    (item) => item.href,
  );

  const quotes = Array.from(doc.querySelectorAll("blockquote"))
    .map((block, index) => {
      const link = block.querySelector("a[href]");
      const clone = block.cloneNode(true);
      clone.querySelectorAll("a[href]").forEach((node) => node.remove());
      return {
        text: normalizeWhitespace(clone.textContent),
        href: link ? resolveHtmlUrl(link.getAttribute("href") || link.href || "") : "",
        label: normalizeWhitespace(link?.textContent || "") || `引用原文 ${index + 1}`,
      };
    })
    .filter((item) => item.text || item.href);

  return { links, quotes };
}

function normalizeSourceTitle(label, href, index) {
  const cleaned = stripReferenceMarker(label);
  if (cleaned && !CITATION_ONLY_PATTERN.test(cleaned) && cleaned.length > 1) {
    return cleaned;
  }
  if (href) {
    return formatSourceHost(href);
  }
  return `来源 ${index}`;
}

function buildSourceItems(references, artifacts) {
  const items = [];

  const pushItem = (item) => {
    const normalizedItem = {
      title: String(item?.title || "").trim(),
      quote: String(item?.quote || "").trim(),
      href: String(item?.href || "").trim(),
    };
    if (!normalizedItem.title && !normalizedItem.quote && !normalizedItem.href) {
      return;
    }
    items.push(normalizedItem);
  };

  artifacts.quotes.forEach((quote, index) => {
    pushItem({
      title: normalizeSourceTitle(quote.label, quote.href, index + 1),
      quote: quote.text,
      href: quote.href,
    });
  });

  artifacts.links.forEach((link, index) => {
    pushItem({
      title: normalizeSourceTitle(link.label, link.href, index + 1),
      quote: "",
      href: link.href,
    });
  });

  references.forEach((reference, index) => {
    pushItem({
      title: stripReferenceMarker(reference) || `来源 ${index + 1}`,
      quote: "",
      href: "",
    });
  });

  return dedupeBy(items, (item) => item.href || `${item.title}::${item.quote}`);
}

function renderAssistantResponse(view, payload, fallbackAnswerText, fallbackThinkingText) {
  const references = collectReferenceLines(payload);
  const fallbackText = stripReferenceLines(payload?.answer_text || "") || stripReferenceLines(fallbackAnswerText || "") || "未获取到回答内容";
  const sanitizedHtml = sanitizeAnswerHtml(payload?.answer_html || "");

  if (sanitizedHtml) {
    view.setMainHtml(sanitizedHtml);
  } else {
    view.setMainText(fallbackText);
  }

  const thinkingText = String(payload?.thinking_text || fallbackThinkingText || "").trim();
  view.finalizeThinking(thinkingText);

  const artifacts = extractHtmlArtifacts(payload?.answer_html || "");
  const sources = buildSourceItems(references, artifacts);
  view.setSources(sources, references);
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
  appendUserMessage(question);
  const assistantView = createAssistantView();
  assistantView.queueMainText("正在生成回答…");
  assistantView.row.classList.add("is-streaming");
  setBusy(true);

  let donePayload = null;
  let streamAnswerText = "";
  let streamThinkingText = "";
  const payload = { question };
  if (selectedModel) {
    payload.model = selectedModel;
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
        assistantView.queueThinkingText(streamThinkingText, { streaming: true });
        if (!streamAnswerText) {
          assistantView.queueMainText("正在生成回答…");
        }
        return;
      }

      if (event.type === "delta") {
        streamAnswerText = typeof event.text === "string" ? event.text : `${streamAnswerText}${event.delta || ""}`;
        assistantView.queueMainText(streamAnswerText || "正在生成回答…");
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
    if (!donePayload) {
      throw new Error("STREAM_ENDED_WITHOUT_DONE");
    }

    if (donePayload.ok) {
      renderAssistantResponse(assistantView, donePayload, streamAnswerText, streamThinkingText);
      await refreshHealth();
      return;
    }

    throw new Error(formatApiError(donePayload));
  } catch (error) {
    assistantView.row.classList.remove("is-streaming");
    assistantView.setMainText(error instanceof Error ? error.message : String(error));
    assistantView.finalizeThinking(streamThinkingText);
    assistantView.setSources([], []);
    setStatus("error", "请求失败");
  } finally {
    setBusy(false);
  }
}

composer.addEventListener("submit", async (event) => {
  event.preventDefault();
  const question = questionEl.value.trim();
  if (!question || isBusy) {
    return;
  }
  questionEl.value = "";
  syncQuestionHeight();
  syncComposerState();
  await askQuestion(question);
});

questionEl.addEventListener("keydown", async (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    const question = questionEl.value.trim();
    if (!question || isBusy) {
      return;
    }
    questionEl.value = "";
    syncQuestionHeight();
    syncComposerState();
    await askQuestion(question);
  }
});

questionEl.addEventListener("input", () => {
  syncQuestionHeight();
  syncComposerState();
  noteActivity();
});

chat.addEventListener("scroll", () => {
  shouldAutoScroll = isChatNearBottom();
  noteActivity();
}, { passive: true });

if (thinkingToggle) {
  thinkingToggle.addEventListener("change", () => {
    setThinkingVisibility(thinkingToggle.checked);
    noteActivity();
  });
}

if (modelSelect) {
  modelSelect.addEventListener("change", () => {
    selectedModel = modelSelect.value;
    noteActivity();
  });
}

clearBtn.addEventListener("click", () => {
  clearConversation();
  noteActivity();
});

drawerBackdrop.addEventListener("click", () => closeSourceDrawer());
drawerCloseBtn.addEventListener("click", () => closeSourceDrawer());
sourceDrawerOpenLink.addEventListener("click", (event) => {
  if (sourceDrawerOpenLink.classList.contains("is-disabled")) {
    event.preventDefault();
  }
});
sourceDrawerFrame.addEventListener("load", () => {
  if (!sourceDrawer.hidden) {
    sourceDrawerStatus.textContent = "已尝试加载原文预览；如果未显示，请直接打开原文。";
  }
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    closeSourceDrawer();
  }
});

window.addEventListener("pageshow", (event) => {
  if (event.persisted) {
    clearConversation({ focus: false });
  }
  noteActivity();
});

async function bootstrap() {
  setThinkingVisibility(thinkingToggle ? thinkingToggle.checked : true);
  setBusy(false);
  clearConversation({ focus: false });
  syncQuestionHeight();
  syncComposerState();
  void loadUiConfig().catch(() => applyModelCatalog());
  void refreshHealth();
  setInterval(refreshHealth, 15000);
  noteActivity();
  questionEl.focus();
}

bootstrap().catch((error) => {
  setStatus("error", "初始化失败");
  const view = createAssistantView();
  view.setMainText(error instanceof Error ? error.message : String(error));
});
