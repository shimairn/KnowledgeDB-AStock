const chat = document.getElementById("chat");
const questionEl = document.getElementById("question");
const composer = document.getElementById("composer");
const sendBtn = document.getElementById("sendBtn");
const clearBtn = document.getElementById("clearBtn");
const statusDot = document.getElementById("statusDot");
const statusText = document.getElementById("statusText");
const kbLabel = document.getElementById("kbLabel");
const poolSummary = document.getElementById("poolSummary");
const questionMeta = document.getElementById("questionMeta");
const drawerBackdrop = document.getElementById("drawerBackdrop");
const sourceDrawer = document.getElementById("sourceDrawer");
const sourceDrawerTitle = document.getElementById("sourceDrawerTitle");
const sourceDrawerMeta = document.getElementById("sourceDrawerMeta");
const sourceDrawerStatus = document.getElementById("sourceDrawerStatus");
const sourceDrawerOpenLink = document.getElementById("sourceDrawerOpenLink");
const sourceDrawerFrame = document.getElementById("sourceDrawerFrame");
const drawerCloseBtn = document.getElementById("drawerCloseBtn");

const INTRO_MESSAGE = "服务已连接，可直接提问。匿名模式下无需登录。";
const HTML_BASE_URL = "https://ima.qq.com/";
const HTML_PARSER = new DOMParser();

let isBusy = false;
let lastDrawerTrigger = null;

function scrollChatToBottom() {
  requestAnimationFrame(() => {
    chat.scrollTop = chat.scrollHeight;
  });
}

function visibleMessageCount() {
  return chat.querySelectorAll(".msg").length;
}

function syncComposerState() {
  questionMeta.textContent = `${questionEl.value.length} 字`;
  sendBtn.disabled = isBusy || !questionEl.value.trim();
  clearBtn.disabled = isBusy || visibleMessageCount() <= 1;
}

function setBusy(value) {
  isBusy = value;
  syncComposerState();
}

function setStatus(kind, text) {
  statusDot.className = `dot ${kind}`;
  statusText.textContent = text;
}

function summarizePool(pool) {
  if (!pool) {
    return "未获取到 worker 池信息";
  }
  return `总数 ${pool.workers_total} / 空闲 ${pool.workers_ready} / 忙碌 ${pool.workers_busy} / 需登录 ${pool.workers_login_required} / 异常 ${pool.workers_error}`;
}

function setHealthStatus(payload) {
  poolSummary.textContent = summarizePool(payload.pool);
  if (payload.ok) {
    setStatus("ready", "可直接提问");
    return;
  }
  if (payload.error_code === "BUSY") {
    setStatus("busy", "当前容量已满，请稍后重试");
    return;
  }
  if (payload.error_code === "LOGIN_REQUIRED") {
    setStatus("error", "部分 worker 需要管理员重新登录");
    return;
  }
  setStatus("error", "服务存在异常 worker");
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

function openSourceDrawer(source, trigger = null) {
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

function appendMessage(role, text) {
  const row = document.createElement("article");
  row.className = `msg ${role}`;

  const avatar = document.createElement("div");
  avatar.className = `avatar ${role}`;
  avatar.textContent = role === "user" ? "你" : "AI";

  const bubble = document.createElement("div");
  bubble.className = "bubble";

  const body = document.createElement("div");
  body.className = "bubble-text";
  body.textContent = text || "";

  bubble.appendChild(body);
  row.appendChild(avatar);
  row.appendChild(bubble);
  chat.appendChild(row);
  syncComposerState();
  scrollChatToBottom();
  return bubble;
}

function setBubbleText(bubble, text) {
  const body = bubble.querySelector(".bubble-text");
  if (body) {
    body.textContent = text || "";
  }
}

function appendIntroMessage() {
  appendMessage("assistant", INTRO_MESSAGE);
}

function formatApiError(payload) {
  const code = payload?.error_code || "REQUEST_FAILED";
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
function createChip(text) {
  const chip = document.createElement("span");
  chip.className = "meta-chip";
  chip.textContent = text;
  return chip;
}

function appendMetaRow(bubble, payload, references, artifacts) {
  const chips = [
    payload?.model ? createChip(payload.model) : null,
    payload?.source_driver ? createChip(`${payload.source_driver.toUpperCase()} 驱动`) : null,
    references.length ? createChip(`${references.length} 条引用`) : null,
    artifacts.tableCount ? createChip(`${artifacts.tableCount} 个表格`) : null,
  ].filter(Boolean);

  if (!chips.length) {
    return;
  }

  const row = document.createElement("div");
  row.className = "bubble-meta";
  chips.forEach((chip) => row.appendChild(chip));
  bubble.appendChild(row);
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

function formatSourceHost(href) {
  try {
    const url = new URL(href);
    return `${url.hostname}${url.pathname}`;
  } catch (_) {
    return href;
  }
}

function appendSourceSection(container, references, artifacts) {
  const items = buildSourceItems(references, artifacts);
  if (!items.length && !references.length) {
    return;
  }

  const section = document.createElement("section");
  section.className = "detail-card";
  section.appendChild(createDetailHeader("引用原文", "把来源入口和引用片段单独整理出来，便于校对。"));

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
  if (!answerHtml) {
    return;
  }

  const details = document.createElement("details");
  details.className = "rich-details";
  details.open = true;

  const summary = document.createElement("summary");
  const label = document.createElement("span");
  label.textContent = artifacts.tableCount ? `富文本原文 · ${artifacts.tableCount} 个表格` : "富文本原文";
  summary.appendChild(label);
  details.appendChild(summary);

  const body = document.createElement("div");
  body.className = "rich-details-body";

  const wrap = document.createElement("div");
  wrap.className = "html-wrap";
  const frame = document.createElement("iframe");
  frame.setAttribute("sandbox", "allow-same-origin");
  frame.setAttribute("title", "回答富文本视图");
  frame.loading = "lazy";
  frame.srcdoc = wrapAnswerHtml(answerHtml);

  const resize = () => {
    try {
      const doc = frame.contentDocument;
      if (!doc || !doc.body) {
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
  details.addEventListener("toggle", scrollChatToBottom);

  wrap.appendChild(frame);
  body.appendChild(wrap);
  details.appendChild(body);
  container.appendChild(details);
}

function renderAssistantResponse(bubble, payload, streamText) {
  const references = collectReferenceLines(payload);
  const summaryText = stripReferenceLines(payload?.answer_text || "") || payload?.answer_text || streamText || "(空回答)";
  setBubbleText(bubble, summaryText);

  const artifacts = extractHtmlArtifacts(payload?.answer_html || "");
  appendMetaRow(bubble, payload, references, artifacts);

  const detailStack = document.createElement("div");
  detailStack.className = "detail-stack";
  appendSourceSection(detailStack, references, artifacts);
  appendRichSection(detailStack, payload?.answer_html || "", artifacts);

  if (detailStack.childElementCount > 0) {
    bubble.appendChild(detailStack);
  }
}

async function fetchJson(url, options = undefined) {
  const resp = await fetch(url, options);
  const contentType = resp.headers.get("content-type") || "";
  const data = contentType.includes("application/json") ? await resp.json() : null;
  return { resp, data };
}

async function loadUiConfig() {
  const { resp, data } = await fetchJson("/api/ui-config");
  if (!resp.ok || !data?.ok) {
    throw new Error("读取 UI 配置失败");
  }
  kbLabel.textContent = data.kb_label;
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
    poolSummary.textContent = "健康状态获取失败";
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
  appendMessage("user", question);
  const bubble = appendMessage("assistant", "正在请求 ima...");
  bubble.classList.add("streaming");
  setBusy(true);

  let donePayload = null;
  let streamText = "";
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
      if (event.type === "delta") {
        streamText = typeof event.text === "string" ? event.text : `${streamText}${event.delta || ""}`;
        setBubbleText(bubble, streamText || "正在请求 ima...");
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

    bubble.classList.remove("streaming");
    if (!donePayload) {
      throw new Error("STREAM_ENDED_WITHOUT_DONE");
    }

    if (donePayload.ok) {
      renderAssistantResponse(bubble, donePayload, streamText);
      await refreshHealth();
      return;
    }

    throw new Error(formatApiError(donePayload));
  } catch (error) {
    bubble.classList.remove("streaming");
    setBubbleText(bubble, error instanceof Error ? error.message : String(error));
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

questionEl.addEventListener("input", syncComposerState);

clearBtn.addEventListener("click", () => {
  closeSourceDrawer({ restoreFocus: false });
  chat.innerHTML = "";
  appendIntroMessage();
  syncComposerState();
  questionEl.focus();
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

async function bootstrap() {
  setBusy(false);
  syncComposerState();
  appendIntroMessage();
  await loadUiConfig();
  await refreshHealth();
  setInterval(refreshHealth, 15000);
  questionEl.focus();
}

bootstrap().catch((error) => {
  setStatus("error", "初始化失败");
  appendMessage("assistant", error instanceof Error ? error.message : String(error));
});

