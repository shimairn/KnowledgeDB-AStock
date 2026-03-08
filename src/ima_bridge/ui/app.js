const chat = document.getElementById("chat");
const questionEl = document.getElementById("question");
const composer = document.getElementById("composer");
const sendBtn = document.getElementById("sendBtn");
const clearBtn = document.getElementById("clearBtn");
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

const INTRO_MESSAGE = "服务已连接，可直接提问。对话仅在当前页临时保留，长时间无操作会自动清理。";
const HTML_BASE_URL = "https://ima.qq.com/";
const HTML_PARSER = new DOMParser();
const AUTO_CLEAR_MS = 15 * 60 * 1000;

let isBusy = false;
let lastDrawerTrigger = null;
let autoClearTimer = 0;

function scrollChatToBottom() {
  requestAnimationFrame(() => {
    chat.scrollTop = chat.scrollHeight;
  });
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
  clearBtn.disabled = isBusy || historyMessageCount() === 0;
  syncIntroState();
}

function setBusy(value) {
  isBusy = value;
  syncComposerState();
}

function setStatus(kind, text) {
  statusDot.className = `dot ${kind}`;
  statusText.textContent = text;
}

function clearConversation(options = {}) {
  const { focus = true } = options;
  closeSourceDrawer({ restoreFocus: false });
  chat.innerHTML = "";
  questionEl.value = "";
  appendIntroMessage();
  syncComposerState();
  if (focus) {
    questionEl.focus();
  }
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

function setHealthStatus(payload) {
  if (payload.ok) {
    setStatus("ready", "可直接提问");
    return;
  }
  if (payload.error_code === "BUSY") {
    setStatus("busy", "服务繁忙，请稍后重试");
    return;
  }
  if (payload.error_code === "LOGIN_REQUIRED") {
    setStatus("error", "请先完成登录");
    return;
  }
  if (payload.error_code === "KB_NOT_FOUND") {
    setStatus("error", "未找到目标知识库");
    return;
  }
  setStatus("error", "服务连接异常");
}

function setDrawerVisibility(visible) {
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

function closeSourceDrawer(options = {}) {
  const { restoreFocus = true } = options;
  if (sourceDrawer.hidden && !sourceDrawer.classList.contains("is-open")) {
    return;
  }

  setDrawerVisibility(false);
  sourceDrawerTitle.textContent = "原文预览";
  sourceDrawerMeta.textContent = "选择一条带链接的来源后，可在这里预览，并可跳转到原文。";
  sourceDrawerStatus.textContent = "部分站点可能禁止嵌入预览；如未显示，请直接打开原文。";
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

function formatSourceHost(href) {
  try {
    const url = new URL(href);
    return `${url.hostname}${url.pathname}`;
  } catch (_) {
    return href;
  }
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
  sourceDrawerStatus.textContent = "正在加载原文预览；如内容为空，可能是目标站点禁止嵌入。";
  sourceDrawerOpenLink.href = source.href;
  sourceDrawerOpenLink.classList.remove("is-disabled");
  sourceDrawerOpenLink.removeAttribute("aria-disabled");
  sourceDrawerOpenLink.tabIndex = 0;
  sourceDrawerFrame.src = source.href;
  setDrawerVisibility(true);
  setTimeout(() => drawerCloseBtn.focus(), 0);
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
  scrollChatToBottom();

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

function createChip(text) {
  const chip = document.createElement("span");
  chip.className = "meta-chip";
  chip.textContent = text;
  return chip;
}

function createAssistantView({ intro = false } = {}) {
  const { row, bubble } = createMessageRow("assistant", intro ? "is-intro" : "");
  const main = document.createElement("div");
  main.className = "bubble-main";

  const body = document.createElement("div");
  body.className = "bubble-text";
  main.appendChild(body);

  const extras = document.createElement("div");
  extras.className = "bubble-extras";

  bubble.appendChild(main);
  bubble.appendChild(extras);

  let mainText = "";
  let thinkingText = "";
  let mainFrame = 0;
  let thinkingFrame = 0;
  let metaRow = null;
  let thinkingDetails = null;
  let thinkingPre = null;
  let thinkingState = null;
  let detailStack = null;

  function queueMainText(value) {
    mainText = String(value || "");
    if (mainFrame) {
      return;
    }
    mainFrame = requestAnimationFrame(() => {
      mainFrame = 0;
      body.textContent = mainText;
      scrollChatToBottom();
    });
  }

  function setMainText(value) {
    mainText = String(value || "");
    body.textContent = mainText;
  }

  function removeMeta() {
    if (metaRow) {
      metaRow.remove();
      metaRow = null;
    }
  }

  function setMeta(texts) {
    const labels = Array.isArray(texts) ? texts.filter(Boolean) : [];
    if (!labels.length) {
      removeMeta();
      return;
    }

    if (!metaRow) {
      metaRow = document.createElement("div");
      metaRow.className = "bubble-meta";
      extras.appendChild(metaRow);
    }

    metaRow.innerHTML = "";
    labels.forEach((label) => metaRow.appendChild(createChip(label)));
  }

  function removeThinking() {
    if (thinkingDetails) {
      thinkingDetails.remove();
      thinkingDetails = null;
      thinkingPre = null;
      thinkingState = null;
      thinkingText = "";
    }
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

    const caption = document.createElement("span");
    caption.className = "thinking-caption";
    caption.textContent = "默认折叠展示，避免打断阅读。";

    thinkingState = document.createElement("span");
    thinkingState.className = "thinking-state";
    thinkingState.textContent = "思考中…";

    copy.appendChild(title);
    copy.appendChild(caption);
    summary.appendChild(copy);
    summary.appendChild(thinkingState);

    const thinkingBody = document.createElement("div");
    thinkingBody.className = "thinking-body";
    thinkingPre = document.createElement("pre");
    thinkingPre.className = "thinking-pre";
    thinkingBody.appendChild(thinkingPre);

    thinkingDetails.appendChild(summary);
    thinkingDetails.appendChild(thinkingBody);
    thinkingDetails.addEventListener("toggle", scrollChatToBottom);
    extras.appendChild(thinkingDetails);
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
    thinkingState.textContent = streaming ? "思考中…" : "已完成";

    if (thinkingFrame) {
      return;
    }

    thinkingFrame = requestAnimationFrame(() => {
      thinkingFrame = 0;
      if (thinkingPre) {
        thinkingPre.textContent = thinkingText;
      }
      scrollChatToBottom();
    });
  }

  function finalizeThinking(value) {
    const normalized = String(value || thinkingText || "").trim();
    if (!normalized) {
      removeThinking();
      return;
    }
    queueThinkingText(normalized, { streaming: false });
  }

  function setDetails(node) {
    if (detailStack) {
      detailStack.remove();
      detailStack = null;
    }
    if (node && node.childElementCount > 0) {
      detailStack = node;
      extras.appendChild(detailStack);
    }
  }

  return {
    row,
    bubble,
    queueMainText,
    setMainText,
    setMeta,
    queueThinkingText,
    finalizeThinking,
    setDetails,
    getThinkingText: () => thinkingText,
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
    return "未找到目标知识库，请确认已进入正确知识库";
  }
  const message = payload?.error_message || "请求失败";
  return `${code}: ${message}`;
}

function normalizeWhitespace(value) {
  return String(value || "").replace(/\s+/g, " ").trim();
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

function extractHtmlArtifacts(answerHtml) {
  const doc = toHtmlDocument(answerHtml);

  const links = dedupeBy(
    Array.from(doc.querySelectorAll("a[href]"))
      .map((anchor, index) => ({
        href: resolveHtmlUrl(anchor.getAttribute("href") || anchor.href || ""),
        label: normalizeWhitespace(anchor.textContent) || `原文 ${index + 1}`,
      }))
      .filter((item) => item.href),
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

  return {
    links,
    quotes,
    tableCount: doc.querySelectorAll("table").length,
  };
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

function buildSourceItems(references, artifacts) {
  const items = [];

  artifacts.quotes.forEach((quote, index) => {
    items.push({
      title: stripReferenceMarker(quote.label) || `来源 ${index + 1}`,
      quote: quote.text,
      href: quote.href,
    });
  });

  artifacts.links.forEach((link, index) => {
    if (items.some((item) => item.href && item.href === link.href)) {
      return;
    }
    items.push({
      title: stripReferenceMarker(link.label) || `原文 ${index + 1}`,
      quote: "",
      href: link.href,
    });
  });

  return items;
}

function appendSourceSection(container, references, artifacts) {
  const items = buildSourceItems(references, artifacts);
  if (!items.length && !references.length) {
    return;
  }

  const section = document.createElement("section");
  section.className = "detail-card";
  section.appendChild(createDetailHeader("引用原文", "来源入口和引用片段会统一收在这里，便于校对。"));

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
      if (item.href) {
        const url = document.createElement("span");
        url.className = "source-url";
        url.textContent = formatSourceHost(item.href);
        footer.appendChild(url);

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
      } else {
        const note = document.createElement("span");
        note.className = "source-url";
        note.textContent = "当前仅抽取到引用条目，未发现可直接打开的链接。";
        footer.appendChild(note);
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

  container.appendChild(section);
}

function wrapAnswerHtml(answerHtml) {
  const html = String(answerHtml || "").trim();
  if (!html) {
    return "<!doctype html><html><head><meta charset=\"utf-8\" /></head><body></body></html>";
  }
  if (/<html[\s>]/i.test(html)) {
    return html;
  }

  return `<!doctype html><html><head><meta charset="utf-8" />
  <base href="${HTML_BASE_URL}" />
  <style>
    :root { color-scheme: light; --line:#dbe4f4; --line-strong:#cad7f0; --text:#172033; --muted:#60708d; --primary:#315efb; --panel:#f8fbff; --quote:#f5f8ff; --shadow:0 10px 24px rgba(15, 23, 42, 0.08); --radius:14px; }
    html,body { margin:0; padding:0; background:#fff; color:var(--text); }
    body { padding:14px; font:14px/1.75 "Segoe UI","PingFang SC","Microsoft YaHei",sans-serif; }
    h1,h2,h3,h4 { margin:0 0 12px; line-height:1.3; color:#1b2c57; }
    p,ul,ol { margin:0 0 12px; }
    table { width:100%; border-collapse:separate; border-spacing:0; overflow:hidden; border:1px solid var(--line-strong); border-radius:var(--radius); background:#fff; box-shadow:var(--shadow); margin:14px 0; }
    thead th { background:linear-gradient(180deg,#eef4ff,#e7efff); color:#274277; font-weight:700; border-bottom:1px solid var(--line-strong); }
    th,td { padding:10px 12px; text-align:left; vertical-align:top; }
    tbody tr:nth-child(even) { background:#f8fbff; }
    tbody td { border-top:1px solid var(--line); }
    blockquote { margin:16px 0; padding:14px 16px; border-left:4px solid var(--primary); border-radius:var(--radius); background:var(--quote); color:#28416f; }
    img,svg,canvas,video { max-width:100%; height:auto; }
    pre { white-space:pre-wrap; word-break:break-word; padding:12px; border-radius:12px; background:var(--panel); border:1px solid var(--line); overflow:auto; }
    a { color:var(--primary); text-decoration:underline; text-decoration-thickness:1.5px; text-underline-offset:3px; word-break:break-all; }
  </style></head><body>${html}</body></html>`;
}

function appendRichSection(container, answerHtml, artifacts) {
  const html = String(answerHtml || "").trim();
  if (!html) {
    return;
  }

  const details = document.createElement("details");
  details.className = "rich-details";

  const summary = document.createElement("summary");
  const copy = document.createElement("div");
  copy.className = "thinking-copy";

  const title = document.createElement("span");
  title.className = "thinking-title";
  title.textContent = "富文本内容";

  const subtitle = document.createElement("span");
  subtitle.className = "thinking-caption";
  subtitle.textContent = artifacts.tableCount
    ? `检测到 ${artifacts.tableCount} 个表格，保留结构化排版。`
    : "原始富文本会在这里保留，便于核对格式。";

  const state = document.createElement("span");
  state.className = "thinking-state";
  state.textContent = "展开";

  copy.appendChild(title);
  copy.appendChild(subtitle);
  summary.appendChild(copy);
  summary.appendChild(state);

  const body = document.createElement("div");
  body.className = "rich-details-body";
  const wrap = document.createElement("div");
  wrap.className = "html-wrap";
  const frame = document.createElement("iframe");
  frame.loading = "lazy";
  frame.referrerPolicy = "no-referrer";
  frame.srcdoc = wrapAnswerHtml(answerHtml);

  const resize = () => {
    try {
      const doc = frame.contentDocument;
      if (!doc) {
        return;
      }
      const bodyHeight = doc.body.scrollHeight || 0;
      const rootHeight = doc.documentElement ? doc.documentElement.scrollHeight || 0 : 0;
      frame.style.height = `${Math.max(220, Math.min(3600, Math.max(bodyHeight, rootHeight) + 18))}px`;
      scrollChatToBottom();
    } catch (_) {
    }
  };

  frame.addEventListener("load", () => {
    resize();
    setTimeout(resize, 120);
    setTimeout(resize, 400);
    setTimeout(resize, 1200);
  });

  details.addEventListener("toggle", () => {
    state.textContent = details.open ? "收起" : "展开";
    scrollChatToBottom();
  });

  wrap.appendChild(frame);
  body.appendChild(wrap);
  details.appendChild(summary);
  details.appendChild(body);
  container.appendChild(details);
}

function renderAssistantResponse(view, payload, fallbackAnswerText, fallbackThinkingText) {
  const references = collectReferenceLines(payload);
  const summaryText = stripReferenceLines(payload?.answer_text || "") || payload?.answer_text || fallbackAnswerText || "(空回答)";
  view.setMainText(summaryText);

  const thinkingText = String(payload?.thinking_text || fallbackThinkingText || "").trim();
  view.finalizeThinking(thinkingText);

  const artifacts = extractHtmlArtifacts(payload?.answer_html || "");
  const metaTexts = [];
  if (references.length) {
    metaTexts.push(`${references.length} 条引用`);
  }
  if (artifacts.tableCount) {
    metaTexts.push(`${artifacts.tableCount} 个表格`);
  }
  view.setMeta(metaTexts);

  const detailStack = document.createElement("div");
  detailStack.className = "detail-stack";
  appendSourceSection(detailStack, references, artifacts);
  appendRichSection(detailStack, payload?.answer_html || "", artifacts);
  view.setDetails(detailStack);
}

async function fetchJson(url, options = undefined) {
  const resp = await fetch(url, options);
  const contentType = resp.headers.get("content-type") || "";
  const data = contentType.includes("application/json") ? await resp.json() : null;
  return { resp, data };
}

async function refreshHealth() {
  try {
    const { resp, data } = await fetchJson("/api/health");
    if (!resp.ok || !data) {
      throw new Error("读取健康状态失败");
    }
    setHealthStatus(data);
  } catch (_) {
    setStatus("error", "无法连接后端服务");
  }
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
  noteActivity();
  appendUserMessage(question);
  const assistantView = createAssistantView();
  assistantView.queueMainText("正在生成回答…");
  assistantView.row.classList.add("is-streaming");
  setBusy(true);

  let donePayload = null;
  let streamAnswerText = "";
  let streamThinkingText = "";

  try {
    const resp = await fetch("/api/ask-stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });

    if (!resp.ok) {
      const payload = await resp.json();
      throw new Error(formatApiError(payload));
    }

    await readJsonLines(resp, (event) => {
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
    assistantView.setMeta([]);
    setStatus("error", "请求失败");
  } finally {
    setBusy(false);
    questionEl.focus();
  }
}

composer.addEventListener("submit", async (event) => {
  event.preventDefault();
  const question = questionEl.value.trim();
  if (!question || isBusy) {
    return;
  }
  questionEl.value = "";
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
    syncComposerState();
    await askQuestion(question);
  }
});

questionEl.addEventListener("input", () => {
  syncComposerState();
  noteActivity();
});

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
    sourceDrawerStatus.textContent = "已尝试加载原文预览；若未显示，请直接打开原文。";
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
  setBusy(false);
  clearConversation({ focus: false });
  await refreshHealth();
  setInterval(refreshHealth, 15000);
  noteActivity();
  questionEl.focus();
}

bootstrap().catch((error) => {
  setStatus("error", "初始化失败");
  const view = createAssistantView();
  view.setMainText(error instanceof Error ? error.message : String(error));
});
