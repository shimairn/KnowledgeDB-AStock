import {
  ANSWER_SURFACE_STYLE_TEXT,
  renderTextRichContent,
  setRichContent,
  textToRichHtml,
} from "/assets/app-render.js";

const HTML_STREAM_DELAY_MS = 180;
const HTML_STREAM_QUEUE_LIMIT = 6;
const ANSWER_REFRESH_CLASS = "is-refreshing";
const ANSWER_REFRESH_DURATION_MS = 220;
const ANSWER_META_PARSER = new DOMParser();
const ANSWER_SECTION_LIMIT = 4;
const USER_MESSAGE_LABEL = "\u4f60";
const ASSISTANT_MESSAGE_LABEL = "\u77e5\u8bc6\u5e93\u56de\u7b54";

export function createMessageRenderer({
  chat,
  noteActivity,
  scrollChatToBottom,
  onMessageMount,
  setComposerDraft = async () => {},
}) {
  function createMessageRow(role) {
    const row = document.createElement("article");
    row.className = `msg ${role}`;

    const column = document.createElement("div");
    column.className = "message-column";

    row.appendChild(column);
    chat.appendChild(row);

    onMessageMount?.({ role, row, column });
    return { row, column };
  }

  function appendMessageMeta(column, role, text) {
    const meta = document.createElement("div");
    meta.className = `message-meta message-meta--${role}`;
    meta.textContent = text;
    column.appendChild(meta);
    return meta;
  }

  function appendUserMessage(text) {
    const { column } = createMessageRow("user");
    appendMessageMeta(column, "user", USER_MESSAGE_LABEL);

    const card = document.createElement("div");
    card.className = "message-card message-card--user";

    const body = document.createElement("div");
    renderTextRichContent(body, text || "");

    card.appendChild(body);
    column.appendChild(card);
  }

  function createAssistantView() {
    const { row, column } = createMessageRow("assistant");
    appendMessageMeta(column, "assistant", ASSISTANT_MESSAGE_LABEL);

    const thinkingHost = document.createElement("div");
    thinkingHost.className = "thinking-host";

    const card = document.createElement("div");
    card.className = "message-card message-card--assistant";

    const streamStatus = document.createElement("div");
    streamStatus.className = "stream-status";
    streamStatus.hidden = true;

    const streamDot = document.createElement("span");
    streamDot.className = "stream-status__dot";
    streamDot.setAttribute("aria-hidden", "true");

    const streamLabel = document.createElement("span");
    streamLabel.className = "stream-status__label";

    streamStatus.appendChild(streamDot);
    streamStatus.appendChild(streamLabel);

    const body = document.createElement("div");
    body.className = "message-rich message-rich--frame message-answer-shell";

    const answerSummary = createAnswerSummary();
    const placeholder = createPlaceholder();
    const answerSurface = createAnswerSurface(scrollChatToBottom);
    const fallback = document.createElement("div");
    fallback.hidden = true;

    const answerState = {
      title: "",
      lead: "",
      sections: [],
      plainText: "",
    };

    const answerActions = createAnswerActions({
      noteActivity,
      onCopy: async () => {
        if (!answerState.plainText) {
          return false;
        }
        return copyTextToClipboard(answerState.plainText);
      },
      onFollowUp: async () => {
        const prompt = createFollowUpPrompt(answerState);
        if (!prompt) {
          return false;
        }
        await setComposerDraft(prompt);
        noteActivity();
        return true;
      },
    });

    body.appendChild(answerSummary.root);
    body.appendChild(placeholder.root);
    body.appendChild(answerSurface.host);
    body.appendChild(fallback);
    body.appendChild(answerActions.root);

    card.appendChild(streamStatus);
    card.appendChild(body);
    column.appendChild(thinkingHost);
    column.appendChild(card);

    let thinkingText = "";
    let thinkingDetails = null;
    let thinkingContent = null;
    let thinkingState = null;
    let thinkingCaption = null;
    let thinkingWriter = null;

    const htmlWriter = createBufferedHtmlWriter((value) => {
      if (!value) {
        return;
      }
      const nextState = extractAnswerState(value);
      answerState.title = nextState.title;
      answerState.lead = nextState.lead;
      answerState.sections = nextState.sections;
      answerState.plainText = nextState.plainText;
      placeholder.hide();
      fallback.hidden = true;
      answerSummary.set(answerState);
      answerActions.show(answerState);
      answerSurface.show();
      answerSurface.setHtml(value);
    });

    function setStreamingState(stage) {
      const normalized = String(stage || "").trim();
      if (!normalized) {
        clearStreamingState();
        return;
      }

      streamStatus.hidden = false;
      streamStatus.className = `stream-status stream-status--${normalized}`;
      if (normalized === "thinking") {
        streamLabel.textContent = "正在整理思路";
        placeholder.setLabel("正在整理回答结构");
      } else if (normalized === "answer") {
        streamLabel.textContent = "正在生成回答";
        placeholder.setLabel("正在生成富文本回答");
      } else {
        streamLabel.textContent = "正在处理";
        placeholder.setLabel("正在准备回答");
      }
      placeholder.show();
      fallback.hidden = true;
      card.classList.add("is-streaming");
    }

    function clearStreamingState() {
      streamStatus.hidden = true;
      streamStatus.className = "stream-status";
      streamLabel.textContent = "";
      card.classList.remove("is-streaming");
    }

    function showPlaceholder() {
      answerSummary.hide();
      answerActions.hide();
      fallback.hidden = true;
      placeholder.show();
      answerSurface.hide();
    }

    function queueMainHtml(contentHtml) {
      const normalized = String(contentHtml || "").trim();
      if (!normalized) {
        return;
      }
      htmlWriter.queue(normalized);
    }

    function setMainHtml(contentHtml) {
      const normalized = String(contentHtml || "").trim();
      if (!normalized) {
        return;
      }
      htmlWriter.set(normalized);
    }

    function setErrorText(value) {
      htmlWriter.stop();
      answerState.title = "";
      answerState.lead = "";
      answerState.sections = [];
      answerState.plainText = "";
      answerSummary.hide();
      answerActions.hide();
      placeholder.hide();
      answerSurface.hide();
      fallback.hidden = false;
      fallback.innerHTML = "";
      renderTextRichContent(fallback, String(value || ""), "message-rich--fallback");
    }

    function removeThinking() {
      if (thinkingWriter) {
        thinkingWriter.stop();
        thinkingWriter = null;
      }
      thinkingHost.innerHTML = "";
      thinkingDetails = null;
      thinkingContent = null;
      thinkingState = null;
      thinkingCaption = null;
      thinkingText = "";
    }

    function ensureThinking() {
      if (thinkingDetails) {
        return;
      }

      thinkingDetails = document.createElement("details");
      thinkingDetails.className = "thinking-panel";

      const summary = document.createElement("summary");
      summary.className = "thinking-toggle";

      const copy = document.createElement("div");
      copy.className = "thinking-copy";

      const title = document.createElement("span");
      title.className = "thinking-title";
      title.textContent = "思考过程";

      thinkingCaption = document.createElement("span");
      thinkingCaption.className = "thinking-caption";
      thinkingCaption.textContent = "默认折叠，不进入正文";

      thinkingState = document.createElement("span");
      thinkingState.className = "thinking-state";
      thinkingState.textContent = "思考中";

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

      thinkingHost.appendChild(thinkingDetails);

      thinkingWriter = createTypewriter(
        (value) => {
          if (thinkingContent) {
            setRichContent(thinkingContent, textToRichHtml(value));
          }
        },
        scrollChatToBottom,
      );
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
      thinkingState.textContent = streaming ? "思考中" : "已完成";
      thinkingCaption.textContent = streaming ? "流式更新中" : "默认折叠，不进入正文";
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
      thinkingCaption.textContent = "默认折叠，不进入正文";
      thinkingWriter.set(thinkingText);
    }

    return {
      row,
      showPlaceholder,
      queueMainHtml,
      setMainHtml,
      setErrorText,
      setStreamingState,
      clearStreamingState,
      queueThinkingText,
      finalizeThinking,
    };
  }

  return {
    appendUserMessage,
    createAssistantView,
  };
}

function createAnswerSummary() {
  const root = document.createElement("section");
  root.className = "answer-summary";
  root.hidden = true;

  const eyebrow = document.createElement("span");
  eyebrow.className = "answer-summary__eyebrow";
  eyebrow.textContent = "回答摘要";

  const title = document.createElement("h3");
  title.className = "answer-summary__title";

  const lead = document.createElement("p");
  lead.className = "answer-summary__lead";

  const sections = document.createElement("div");
  sections.className = "answer-summary__sections";

  root.appendChild(eyebrow);
  root.appendChild(title);
  root.appendChild(lead);
  root.appendChild(sections);

  return {
    root,
    hide() {
      root.hidden = true;
      title.textContent = "";
      lead.hidden = true;
      lead.textContent = "";
      sections.innerHTML = "";
      sections.hidden = true;
    },
    set(meta = {}) {
      const hasTitle = Boolean(meta.title);
      const hasLead = Boolean(meta.lead);
      const sectionList = Array.isArray(meta.sections) ? meta.sections : [];

      if (!hasTitle && !hasLead && !sectionList.length) {
        this.hide();
        return;
      }

      title.textContent = meta.title || "结构化回答";
      lead.hidden = !hasLead;
      lead.textContent = meta.lead || "";
      sections.innerHTML = "";
      sectionList.forEach((item) => {
        const chip = document.createElement("span");
        chip.className = "answer-summary__section";
        chip.textContent = item;
        sections.appendChild(chip);
      });
      sections.hidden = sectionList.length === 0;
      root.hidden = false;
    },
  };
}

function createAnswerActions({ noteActivity, onCopy, onFollowUp }) {
  const root = document.createElement("div");
  root.className = "message-actions";
  root.hidden = true;

  const copyButton = document.createElement("button");
  copyButton.type = "button";
  copyButton.className = "message-action";
  copyButton.textContent = "复制回答";

  const followUpButton = document.createElement("button");
  followUpButton.type = "button";
  followUpButton.className = "message-action";
  followUpButton.textContent = "继续追问";

  root.appendChild(copyButton);
  root.appendChild(followUpButton);

  const flashLabel = (button, idleText, activeText) => {
    if (button._messageActionTimer) {
      window.clearTimeout(button._messageActionTimer);
    }
    button.textContent = activeText;
    button.classList.add("is-confirmed");
    button._messageActionTimer = window.setTimeout(() => {
      button.textContent = idleText;
      button.classList.remove("is-confirmed");
      button._messageActionTimer = 0;
    }, 1400);
  };

  copyButton.addEventListener("click", async () => {
    const ok = await onCopy();
    flashLabel(copyButton, "复制回答", ok ? "已复制" : "复制失败");
    noteActivity();
  });

  followUpButton.addEventListener("click", async () => {
    const ok = await onFollowUp();
    flashLabel(followUpButton, "继续追问", ok ? "已填入输入框" : "暂不可用");
    noteActivity();
  });

  return {
    root,
    hide() {
      root.hidden = true;
    },
    show(meta = {}) {
      root.hidden = !meta.plainText;
    },
  };
}

function createPlaceholder() {
  const root = document.createElement("div");
  root.className = "answer-placeholder";

  const label = document.createElement("span");
  label.className = "answer-placeholder__label";
  label.textContent = "正在准备回答";

  const lines = document.createElement("div");
  lines.className = "answer-placeholder__lines";
  for (let index = 0; index < 3; index += 1) {
    const line = document.createElement("span");
    line.className = `answer-placeholder__line answer-placeholder__line--${index + 1}`;
    lines.appendChild(line);
  }

  root.appendChild(label);
  root.appendChild(lines);

  return {
    root,
    setLabel(value) {
      label.textContent = String(value || "").trim() || "正在准备回答";
    },
    show() {
      root.hidden = false;
    },
    hide() {
      root.hidden = true;
    },
  };
}

function createAnswerSurface(afterRender = () => {}) {
  const host = document.createElement("div");
  host.className = "answer-surface";
  host.hidden = true;

  let contentNode = null;
  let refreshTimer = 0;

  const ensureContentNode = () => {
    if (contentNode) {
      return contentNode;
    }

    if (typeof host.attachShadow === "function") {
      const shadowRoot = host.shadowRoot || host.attachShadow({ mode: "open" });
      shadowRoot.innerHTML = [
        `<style>${ANSWER_SURFACE_STYLE_TEXT}</style>`,
        '<article class="answer-doc" part="content"></article>',
      ].join("");
      contentNode = shadowRoot.querySelector(".answer-doc");
      return contentNode;
    }

    host.innerHTML = '<article class="answer-surface__fallback rich-content"></article>';
    contentNode = host.querySelector(".answer-surface__fallback");
    return contentNode;
  };

  return {
    host,
    show() {
      host.hidden = false;
    },
    hide() {
      if (refreshTimer) {
        window.clearTimeout(refreshTimer);
        refreshTimer = 0;
      }
      host.classList.remove(ANSWER_REFRESH_CLASS);
      host.hidden = true;
    },
    setHtml(value) {
      const node = ensureContentNode();
      node.innerHTML = String(value || "");
      host.classList.remove(ANSWER_REFRESH_CLASS);
      void host.offsetWidth;
      host.classList.add(ANSWER_REFRESH_CLASS);
      if (refreshTimer) {
        window.clearTimeout(refreshTimer);
      }
      refreshTimer = window.setTimeout(() => {
        host.classList.remove(ANSWER_REFRESH_CLASS);
        refreshTimer = 0;
      }, ANSWER_REFRESH_DURATION_MS);
      afterRender();
    },
  };
}

function createBufferedHtmlWriter(render) {
  let currentValue = "";
  let queuedValues = [];
  let timer = 0;

  const schedule = () => {
    if (timer || !queuedValues.length) {
      return;
    }
    timer = window.setTimeout(flush, HTML_STREAM_DELAY_MS);
  };

  const trimQueue = () => {
    while (queuedValues.length > HTML_STREAM_QUEUE_LIMIT) {
      queuedValues.splice(1, 1);
    }
  };

  const flush = () => {
    timer = 0;
    if (!queuedValues.length) {
      return;
    }

    const nextValue = queuedValues.shift();
    if (!nextValue || nextValue === currentValue) {
      schedule();
      return;
    }

    currentValue = nextValue;
    render(currentValue);
    schedule();
  };

  return {
    queue(value) {
      const normalized = String(value || "").trim();
      const lastQueuedValue = queuedValues.length ? queuedValues[queuedValues.length - 1] : currentValue;
      if (!normalized || normalized === lastQueuedValue) {
        return;
      }

      queuedValues.push(normalized);
      trimQueue();
      schedule();
    },
    set(value) {
      const normalized = String(value || "").trim();
      if (timer) {
        window.clearTimeout(timer);
        timer = 0;
      }
      queuedValues = [];
      if (!normalized || normalized === currentValue) {
        return;
      }
      currentValue = normalized;
      render(currentValue);
    },
    stop() {
      if (timer) {
        window.clearTimeout(timer);
        timer = 0;
      }
      queuedValues = [];
    },
  };
}

function extractAnswerState(contentHtml) {
  const doc = ANSWER_META_PARSER.parseFromString(`<article>${String(contentHtml || "")}</article>`, "text/html");
  const root = doc.body;
  const headingTexts = Array.from(root.querySelectorAll("h1, h2, h3, h4"))
    .map((node) => normalizeText(node.textContent || ""))
    .filter(Boolean);
  const paragraphs = Array.from(root.querySelectorAll("p"))
    .map((node) => normalizeText(node.textContent || ""))
    .filter((text) => text.length >= 18);

  const title = headingTexts[0] || "结构化回答";
  const lead = paragraphs.find((text) => text !== title) || "";
  const sections = headingTexts
    .slice(1)
    .filter((text) => text !== title)
    .slice(0, ANSWER_SECTION_LIMIT);
  const plainText = normalizeText(root.textContent || "");

  return {
    title,
    lead,
    sections,
    plainText,
  };
}

function createFollowUpPrompt(answerState = {}) {
  const title = normalizeText(answerState.title || "");
  const sections = Array.isArray(answerState.sections) ? answerState.sections.filter(Boolean) : [];
  if (!title && !sections.length) {
    return "";
  }

  if (sections.length >= 2) {
    return `请基于刚才关于“${title || sections[0]}”的回答，继续展开 ${sections.slice(0, 2).join("、")}，补充关键风险、跟踪指标和应对思路。`;
  }

  return `请基于刚才关于“${title || sections[0]}”的回答，继续展开关键风险、跟踪指标和应对思路。`;
}

function normalizeText(value) {
  return String(value || "").replace(/\s+/g, " ").trim();
}

async function copyTextToClipboard(value) {
  const normalized = String(value || "").trim();
  if (!normalized) {
    return false;
  }

  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(normalized);
      return true;
    }
  } catch (_) {
    // Fall through to execCommand for older browsers.
  }

  const helper = document.createElement("textarea");
  helper.value = normalized;
  helper.setAttribute("readonly", "true");
  helper.style.position = "fixed";
  helper.style.top = "-9999px";
  document.body.appendChild(helper);
  helper.focus();
  helper.select();
  let ok = false;
  try {
    ok = document.execCommand("copy");
  } catch (_) {
    ok = false;
  }
  helper.remove();
  return ok;
}

function commonPrefixLength(left, right) {
  const max = Math.min(left.length, right.length);
  let index = 0;
  while (index < max && left[index] === right[index]) {
    index += 1;
  }
  return index;
}

function createTypewriter(render, afterRender = () => {}) {
  let targetText = "";
  let renderedText = "";
  let frameToken = 0;

  function flush() {
    render(renderedText);
    afterRender();
  }

  function step() {
    frameToken = 0;
    if (renderedText === targetText) {
      return;
    }

    const remaining = targetText.length - renderedText.length;
    const batch = remaining > 240 ? 10 : remaining > 120 ? 7 : remaining > 48 ? 4 : 2;
    renderedText = targetText.slice(0, renderedText.length + batch);
    flush();

    if (renderedText !== targetText) {
      frameToken = requestAnimationFrame(step);
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
      if (!frameToken) {
        frameToken = requestAnimationFrame(step);
      }
    },
    set(value) {
      if (frameToken) {
        cancelAnimationFrame(frameToken);
        frameToken = 0;
      }
      targetText = String(value || "");
      renderedText = targetText;
      flush();
    },
    stop() {
      if (frameToken) {
        cancelAnimationFrame(frameToken);
        frameToken = 0;
      }
    },
  };
}
