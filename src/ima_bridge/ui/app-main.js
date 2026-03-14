const HTML_BASE_URL = "https://ima.qq.com/";

const DEFAULT_KB_LABEL = "财经知识库";

const DEFAULT_STARTUP_POLL_INTERVAL_MS = 1500;
const DEFAULT_STEADY_POLL_INTERVAL_MS = 15000;

const QUESTION_MIN_HEIGHT = 52;
const QUESTION_MAX_HEIGHT = 220;
const SCROLL_BOTTOM_THRESHOLD_PX = 80;

// 1 char per tick, can be slower than backend updates.
const TYPEWRITER_TICK_MS = 20;

const dom = {
  kbLabel: document.getElementById("kbLabel"),
  statusWrap: document.getElementById("statusWrap"),
  statusDot: document.getElementById("statusDot"),
  statusText: document.getElementById("statusText"),
  stopBtn: document.getElementById("stopBtn"),
  emptyState: document.getElementById("emptyState"),
  conversationViewport: document.getElementById("conversationViewport"),
  chat: document.getElementById("chat"),
  composer: document.getElementById("composer"),
  question: document.getElementById("question"),
  sendBtn: document.getElementById("sendBtn"),
  newConversationBtn: document.getElementById("newConversationBtn"),
};

const state = {
  isBusy: false,
  healthPollTimer: 0,
  startupPollIntervalMs: DEFAULT_STARTUP_POLL_INTERVAL_MS,
  steadyPollIntervalMs: DEFAULT_STEADY_POLL_INTERVAL_MS,
  isPinnedToBottom: true,
  lastViewportScrollTop: 0,
  abortController: null,
  conversationId: "",
};

export async function bootstrap() {
  setKbLabel(DEFAULT_KB_LABEL);
  setStatus("ready", "初始化中...");
  clearConversation({ focus: false });
  state.conversationId =
    typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
      ? crypto.randomUUID()
      : String(Math.random()).slice(2) + "-" + Date.now();
  syncQuestionHeight();
  syncUiState();

  bindEvents();

  try {
    const config = await loadUiConfig();
    scheduleHealthRefresh(getHealthRefreshDelay(config.health || null));
  } catch (_) {
    scheduleHealthRefresh(state.startupPollIntervalMs);
  }

  await refreshHealth();
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
      state.conversationId =
        typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
          ? crypto.randomUUID()
          : String(Math.random()).slice(2) + "-" + Date.now();
    });
  }

  if (dom.stopBtn) {
    dom.stopBtn.addEventListener("click", () => {
      if (state.abortController) {
        try {
          state.abortController.abort();
        } catch (_) {
          // ignore
        }
      }
    });
  }

  if (dom.conversationViewport) {
    dom.conversationViewport.addEventListener(
      "scroll",
      () => {
        const viewport = dom.conversationViewport;
        const nextTop = viewport.scrollTop;
        const scrolledUp = nextTop < state.lastViewportScrollTop - 1;
        if (scrolledUp) {
          // User explicitly scrolled up: stop auto-follow even if still near the bottom.
          state.isPinnedToBottom = false;
        } else if (isNearBottom(viewport)) {
          state.isPinnedToBottom = true;
        }
        state.lastViewportScrollTop = nextTop;
      },
      { passive: true },
    );
  }
}

function setKbLabel(value) {
  const text = String(value || "").trim() || DEFAULT_KB_LABEL;
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

  if (dom.stopBtn) {
    dom.stopBtn.hidden = !state.isBusy;
    dom.stopBtn.disabled = !state.isBusy;
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

function isNearBottom(viewport) {
  if (!viewport) {
    return true;
  }
  const remaining = viewport.scrollHeight - viewport.scrollTop - viewport.clientHeight;
  return remaining <= SCROLL_BOTTOM_THRESHOLD_PX;
}

function scrollChatToBottom(options = {}) {
  if (!dom.conversationViewport) {
    return;
  }
  const { force = false } = options;
  if (!force && !state.isPinnedToBottom) {
    return;
  }
  dom.conversationViewport.scrollTo({
    top: dom.conversationViewport.scrollHeight,
    behavior: "auto",
  });
  state.isPinnedToBottom = true;
  window.requestAnimationFrame(() => {
    if (!dom.conversationViewport) {
      return;
    }
    state.lastViewportScrollTop = dom.conversationViewport.scrollTop;
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
  state.isPinnedToBottom = true;
  state.lastViewportScrollTop = 0;
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

function createLoaderNode() {
  const loader = document.createElement("div");
  loader.className = "bubble__loader";
  for (let i = 0; i < 3; i += 1) {
    const dot = document.createElement("span");
    dot.className = "bubble__loader-dot";
    loader.appendChild(dot);
  }
  return loader;
}

function createAssistantMessage() {
  if (!dom.chat) {
    return null;
  }

  const row = document.createElement("article");
  row.className = "msg assistant";

  const bubble = document.createElement("div");
  bubble.className = "bubble bubble--assistant";

  const loader = createLoaderNode();

  const content = document.createElement("div");
  content.className = "rich-content rich-content--typing";
  content.hidden = true;

  bubble.appendChild(loader);
  bubble.appendChild(content);
  row.appendChild(bubble);
  dom.chat.appendChild(row);

  let lastScrollAt = 0;
  const typer = createRichTypewriter(content, {
    tickMs: TYPEWRITER_TICK_MS,
    onStart: () => {
      loader.hidden = true;
      content.hidden = false;
    },
    onProgress: () => {
      const now = typeof performance !== "undefined" ? performance.now() : Date.now();
      if (now - lastScrollAt >= 120) {
        lastScrollAt = now;
        scrollChatToBottom();
      }
    },
    onDone: () => {
      content.classList.remove("rich-content--typing");
    },
  });

  return {
    row,
    bubble,
    loader,
    content,
    typer,
    setError(message) {
      typer.stop();
      loader.hidden = true;
      content.hidden = false;
      content.className = "bubble__text";
      content.textContent = String(message || "");
    },
  };
}

function escapeHtml(value) {
  return String(value || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function plainTextToHtml(text) {
  const normalized = String(text || "").trim();
  if (!normalized) {
    return "";
  }
  return `<p>${escapeHtml(normalized).replace(/\n/g, "<br>")}</p>`;
}


const RICH_DROP_TAGS = new Set([
  "script",
  "noscript",
  "style",
  "link",
  "meta",
  "base",
  "iframe",
  "object",
  "embed",
  "form",
  "input",
  "textarea",
  "button",
  "select",
  "option",
  "svg",
  "canvas",
]);

  function createRichTypewriter(container, { tickMs, onStart, onProgress, onDone }) {
    let typedLen = 0;

    let done = false;
    let running = false;
  let raf = 0;
  let lastTickAt = 0;
  let startedDisplay = false;

  // Target is the *latest* streamed HTML.
  let pendingHtml = "";
  let lastBuiltHtml = "";
  let segments = [];
  let segmentIndex = 0;
  let segmentOffset = 0;
  let totalLen = 0;

    let buildTimer = 0;
    let lastBuildAt = 0;
    const BUILD_MIN_INTERVAL_MS = 120;
    let swapOnNextBuild = false;

    const stop = () => {
      running = false;
      if (raf) {
        window.cancelAnimationFrame(raf);
      raf = 0;
    }
    if (buildTimer) {
      window.clearTimeout(buildTimer);
      buildTimer = 0;
    }
  };

  const normalizeTypingText = (value) => {
    return String(value || "")
      .replace(/[\s\u00A0\u200B-\u200D\uFEFF]+/g, " ")
      .trim();
  };

  const isMarkerOnlyText = (text) => {
    const normalized = normalizeTypingText(text);
    return /^(?:\d+[.)]?|[-*•])$/.test(normalized);
  };

  const shouldHidePlaceholder = (el) => {
    if (!el || el.nodeType !== Node.ELEMENT_NODE) {
      return false;
    }

    const tag = String(el.tagName || "").toLowerCase();

    if (tag === "li") {
      const text = normalizeTypingText(el.textContent || "");
      if (!text) {
        return true;
      }
      return isMarkerOnlyText(text);
    }

    if (tag === "p") {
      if (el.closest("blockquote,pre,table,li")) {
        return false;
      }
      const text = normalizeTypingText(el.textContent || "");
      if (!text) {
        return false;
      }
      if (!isMarkerOnlyText(text)) {
        return false;
      }
      const hasNonBrElementChild = Array.from(el.childNodes || []).some((node) => {
        if (!node || node.nodeType !== Node.ELEMENT_NODE) {
          return false;
        }
        return String(node.tagName || "").toLowerCase() !== "br";
      });
      return !hasNonBrElementChild;
    }

    return false;
  };

  const revealIfReady = (el) => {
    if (!el || el.nodeType !== Node.ELEMENT_NODE) {
      return;
    }
    if (!el.classList.contains("typing-hidden")) {
      return;
    }
    if (!shouldHidePlaceholder(el)) {
      el.classList.remove("typing-hidden");
    }
  };

    const charsPerTick = () => {
      // Use totalLen as approximation for speed curve.
      const remaining = Math.max(0, totalLen - typedLen);
      if (done) {
        if (remaining <= 120) return 6;
        if (remaining <= 360) return 10;
        return 14;
      }
      if (remaining <= 40) return 1;
      if (remaining <= 120) return 2;
      if (totalLen >= 6000) return 10;
      if (totalLen >= 3500) return 8;
    if (totalLen >= 1800) return 6;
    if (totalLen >= 800) return 4;
    if (totalLen >= 320) return 3;
    return 2;
  };

    const buildSegments = (root) => {
      const out = [];
      const walker = root.ownerDocument.createTreeWalker(root, NodeFilter.SHOW_TEXT);
      let node;
      while ((node = walker.nextNode())) {
        const value = String(node.nodeValue || "");
        if (!value) {
          continue;
        }
        const parent = node.parentElement;
        if (!parent) {
          continue;
        }

        // Typewriter only applies to prose paragraphs / list items.
        // Tables, images, and code blocks should render immediately.
        const scope = parent.closest("p,li");
        if (!scope) {
          continue;
        }
        if (parent.closest("table,pre,code,figure,figcaption")) {
          continue;
        }
        out.push({ node, text: value });
      }
      return out;
    };

    const preserveExistingImages = () => {
      const buckets = new Map();
      container.querySelectorAll("img[src]").forEach((img) => {
        const src = img.getAttribute("src");
        if (!src) return;
        const list = buckets.get(src) || [];
        list.push(img);
        buckets.set(src, list);
      });
      return buckets;
    };

    const restorePreservedImages = (buckets) => {
      if (!buckets || buckets.size === 0) {
        return;
      }
      container.querySelectorAll("img[src]").forEach((img) => {
        const src = img.getAttribute("src");
        if (!src) return;
        const list = buckets.get(src);
        if (!list || list.length === 0) return;
        const preserved = list.shift();
        if (!preserved || preserved === img) return;

        const wasLoaded = preserved.classList.contains("rich-img--loaded");
        const wasBroken = preserved.classList.contains("rich-img--broken");
        try {
          Array.from(img.attributes).forEach((attr) => {
            preserved.setAttribute(attr.name, attr.value);
          });
          if (wasLoaded) preserved.classList.add("rich-img--loaded");
          if (wasBroken) preserved.classList.add("rich-img--broken");
        } catch (_) {
          // ignore
        }
        img.replaceWith(preserved);
      });
    };

    const applyVisibilityRules = (root) => {
      root.querySelectorAll("li,p").forEach((el) => {
        if (shouldHidePlaceholder(el)) {
          el.classList.add("typing-hidden");
      }
    });
  };

    const buildFromPending = () => {
      const next = String(pendingHtml || "").trim();
      if (!next || next === lastBuiltHtml) {
        return;
      }

      const preservedImages = preserveExistingImages();

      // Parse incoming HTML fragment.
      const parser = new DOMParser();
      const documentHtml = /<html[\s>]/i.test(next)
        ? next
      : `<!doctype html><html><head></head><body>${next}</body></html>`;
    const doc = parser.parseFromString(documentHtml, "text/html");
    const body = doc.body;
    if (!body) {
      return;
    }

    // Drop unsafe/noisy tags.
    body.querySelectorAll(Array.from(RICH_DROP_TAGS).join(",")).forEach((node) => node.remove());

      applyVisibilityRules(body);

      // Render full rich HTML immediately.
      container.innerHTML = body.innerHTML;
      restorePreservedImages(preservedImages);
      if (swapOnNextBuild) {
        swapOnNextBuild = false;
        container.classList.add("rich-content--swap");
      }

      // Recompute segments on the live DOM inside container.
      segments = buildSegments(container);
      segmentIndex = 0;
      segmentOffset = 0;
      totalLen = segments.reduce((sum, seg) => sum + seg.text.length, 0);

      // Keep typedLen (progress) but clamp it.
      typedLen = Math.max(0, Math.min(typedLen, totalLen));

      // Immediately apply typing mask for current progress.
      let remaining = typedLen;
      let nextSegmentIndex = segments.length;
      let nextSegmentOffset = 0;
      for (let i = 0; i < segments.length; i += 1) {
        const seg = segments[i];
        if (remaining >= seg.text.length) {
          seg.node.nodeValue = seg.text;
          remaining -= seg.text.length;
        } else {
          seg.node.nodeValue = seg.text.slice(0, remaining);
          nextSegmentIndex = i;
          nextSegmentOffset = remaining;
          remaining = 0;
          // Blank out the rest.
          for (let j = i + 1; j < segments.length; j += 1) {
            segments[j].node.nodeValue = "";
          }
          break;
        }
      }
      segmentIndex = nextSegmentIndex;
      segmentOffset = nextSegmentOffset;

      container.querySelectorAll("li.typing-hidden,p.typing-hidden").forEach(revealIfReady);

      lastBuiltHtml = next;
    };

  const scheduleBuild = () => {
    if (buildTimer) {
      return;
    }
    const now = typeof performance !== "undefined" ? performance.now() : Date.now();
    const delay = Math.max(0, BUILD_MIN_INTERVAL_MS - (now - lastBuildAt));
    buildTimer = window.setTimeout(() => {
      buildTimer = 0;
      lastBuildAt = typeof performance !== "undefined" ? performance.now() : Date.now();
      buildFromPending();
    }, delay);
  };

  const typeChars = (count) => {
    let remaining = count;
      while (remaining > 0 && segmentIndex < segments.length) {
        const seg = segments[segmentIndex];
        const available = seg.text.length - segmentOffset;
        if (available <= 0) {
          segmentIndex += 1;
          segmentOffset = 0;
          continue;
        }

      const step = Math.min(available, remaining);
      const nextOffset = segmentOffset + step;
      seg.node.nodeValue = seg.text.slice(0, nextOffset);
      segmentOffset = nextOffset;
      typedLen += step;
        remaining -= step;

        // Reveal placeholders when text arrives.
        const parent = seg.node.parentElement;
        if (parent) {
          revealIfReady(parent.closest?.("p,li") || parent);
        }

        if (segmentOffset >= seg.text.length) {
          segmentIndex += 1;
          segmentOffset = 0;
        }
    }
  };

  const loop = (timestamp) => {
    if (!running) {
      return;
    }
    if (!container || !container.isConnected) {
      stop();
      return;
    }

    if (!lastTickAt) {
      lastTickAt = timestamp;
    }

    const interval = Math.max(10, Number(tickMs) || 20);
    if (timestamp - lastTickAt >= interval) {
      lastTickAt = timestamp;

      if (typedLen < totalLen) {
        typeChars(charsPerTick());
        onProgress?.();
      } else if (done) {
        stop();
        onDone?.();
        return;
      }
    }

    raf = window.requestAnimationFrame(loop);
  };

  const ensureRunning = () => {
    if (running) {
      return;
    }
    running = true;
    raf = window.requestAnimationFrame(loop);
  };

  return {
    setTargetHtml(nextHtml) {
      const normalized = String(nextHtml || "").trim();
      if (!normalized) {
        return;
      }

      if (!startedDisplay) {
        startedDisplay = true;
        onStart?.();
      }

      pendingHtml = normalized;
      scheduleBuild();
      ensureRunning();
    },
      markDone(nextFinalHtml) {
        const normalized = String(nextFinalHtml || "").trim();
        if (!startedDisplay) {
          startedDisplay = true;
          onStart?.();
        }
        if (normalized) {
          pendingHtml = normalized;
          swapOnNextBuild = true;
          scheduleBuild();
        }
        done = true;
        ensureRunning();
      },
      stop,
  };
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
    const view = createAssistantMessage();
    if (!view) {
      return;
    }
  syncUiState();
  scrollChatToBottom({ force: true });

  setBusy(true);
  setStatus("busy", "整理中...");

  state.abortController = new AbortController();

  let streamAnswerHtml = "";
  let donePayload = null;

    try {
      const resp = await fetch("/api/ask-stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question, conversation_id: state.conversationId }),
        signal: state.abortController.signal,
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
        setStatus("busy", streamAnswerHtml ? "生成中..." : "整理中...");
        return;
      }

      if (event.type === "answer_html") {
        const html = String(event.html || "").trim();
        if (!html) {
          return;
        }
        streamAnswerHtml = html;
        view.typer.setTargetHtml(html);
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

    if (!donePayload.ok) {
      throw new Error(formatApiError(donePayload));
    }

    const finalHtml = String(donePayload.answer_html || streamAnswerHtml || "").trim();
    const answerText = String(donePayload.answer_text || "").trim();

    // Let the typewriter finish smoothly, while we keep rendering streamed rich HTML (tables/images).
    // Once typing completes, we swap to final rich HTML with a fade.
    if (finalHtml) {
      view.typer.markDone(finalHtml);
    } else if (answerText) {
      view.typer.markDone(plainTextToHtml(answerText));
    } else {
      view.typer.markDone("");
    }
    await refreshHealth();
  } catch (error) {
    if (error && typeof error === "object" && "name" in error && error.name === "AbortError") {
      setStatus("error", "已停止");
      view.setError("已停止生成");
    } else {
      setStatus("error", "请求失败");
      view.setError(error instanceof Error ? error.message : String(error || "请求失败"));
    }
  } finally {
    state.abortController = null;
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
  setKbLabel(typeof data.kb_label === "string" ? data.kb_label : DEFAULT_KB_LABEL);
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
    setHealthStatus(data);
    return data;
  } catch (_) {
    nextPayload = { ok: false, status: "error", error_code: "REQUEST_FAILED", error_message: "health failed" };
    setHealthStatus(nextPayload);
    return null;
  } finally {
    scheduleHealthRefresh(getHealthRefreshDelay(nextPayload));
  }
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
