import {
  ANSWER_SURFACE_STYLE_TEXT,
  renderTextRichContent,
  setRichContent,
  textToRichHtml,
} from "/assets/app-render.js";

const HTML_STREAM_DELAY_MS = 140;

export function createMessageRenderer({
  chat,
  noteActivity,
  scrollChatToBottom,
  onMessageMount,
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

  function appendUserMessage(text) {
    const { column } = createMessageRow("user");
    const card = document.createElement("div");
    card.className = "message-card message-card--user";

    const body = document.createElement("div");
    renderTextRichContent(body, text || "");

    card.appendChild(body);
    column.appendChild(card);
  }

  function createAssistantView() {
    const { row, column } = createMessageRow("assistant");
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
    body.className = "message-rich message-rich--frame";

    const placeholder = createPlaceholder();
    const answerSurface = createAnswerSurface(scrollChatToBottom);
    body.appendChild(placeholder.root);
    body.appendChild(answerSurface.host);

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
      placeholder.hide();
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
      card.classList.add("is-streaming");
    }

    function clearStreamingState() {
      streamStatus.hidden = true;
      streamStatus.className = "stream-status";
      streamLabel.textContent = "";
      card.classList.remove("is-streaming");
    }

    function showPlaceholder() {
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
      body.innerHTML = "";
      renderTextRichContent(body, String(value || ""), "message-rich--fallback");
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
      host.hidden = true;
    },
    setHtml(value) {
      const node = ensureContentNode();
      node.innerHTML = String(value || "");
      afterRender();
    },
  };
}

function createBufferedHtmlWriter(render) {
  let currentValue = "";
  let pendingValue = "";
  let timer = 0;

  const flush = () => {
    timer = 0;
    if (!pendingValue || pendingValue === currentValue) {
      return;
    }
    currentValue = pendingValue;
    render(currentValue);
  };

  return {
    queue(value) {
      pendingValue = String(value || "").trim();
      if (!pendingValue || pendingValue === currentValue || timer) {
        return;
      }
      timer = window.setTimeout(flush, HTML_STREAM_DELAY_MS);
    },
    set(value) {
      pendingValue = String(value || "").trim();
      if (timer) {
        window.clearTimeout(timer);
        timer = 0;
      }
      flush();
    },
    stop() {
      if (timer) {
        window.clearTimeout(timer);
        timer = 0;
      }
      pendingValue = currentValue;
    },
  };
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
