const HTML_BASE_URL = "https://ima.qq.com/";
const HTML_PARSER = new DOMParser();
const BAD_PROTOCOL_RE = /^(?:javascript|vbscript|data):/i;
const REMOVABLE_SELECTOR = "p,div,section,article,li,span,details,summary,aside,header,footer";
const COMPLEX_CONTENT_SELECTOR = "table,blockquote,pre,code,img,figure,ul,ol,dl";
const LAYOUT_WRAPPER_SELECTOR = "div,section,article,span";
const NOISE_TEXT_PATTERNS = [
  /^(?:\u627e\u5230|\u5171\u627e\u5230)\s*\d+\s*\u6761(?:\u76f8\u5173)?(?:\u77e5\u8bc6\u5e93)?(?:\u5185\u5bb9|\u7ed3\u679c|\u8d44\u6599|\u6587\u6863|\u4fe1\u606f).*$/u,
  /^\u5728\u77e5\u8bc6\u5e93\u4e2d\u627e\u5230\s*\d+\s*\u6761(?:\u76f8\u5173)?(?:\u77e5\u8bc6\u5e93)?(?:\u5185\u5bb9|\u7ed3\u679c|\u8d44\u6599|\u6587\u6863|\u4fe1\u606f).*$/u,
  /^\u5df2\u4e3a\u4f60\u627e\u5230\s*\d+\s*\u6761(?:\u76f8\u5173)?(?:\u5185\u5bb9|\u7ed3\u679c|\u8d44\u6599|\u6587\u6863|\u4fe1\u606f)?.*$/u,
];
const AUXILIARY_TEXT_PATTERNS = [
  /^(?:\u601d\u8003\u8fc7\u7a0b|\u6df1\u5ea6\u601d\u8003|\u63a8\u7406\u8fc7\u7a0b|\u601d\u8003\u4e2d).*$/u,
  /^(?:\u6765\u6e90|\u5f15\u7528\u6765\u6e90|\u53c2\u8003\u8d44\u6599|\u539f\u6587\u9884\u89c8|\u6253\u5f00\u539f\u6587|\u67e5\u770b\u6765\u6e90).*$/u,
];
const BRAND_TEXT_PATTERNS = [
  /^(?:ima|tencent ima|\u817e\u8baf\s*ima)$/iu,
];
const AUXILIARY_ATTR_RE =
  /(think|reason|analysis|thought|source|reference|citation|drawer|toolbar|popover|tooltip|menu|tab|legend|axis|chart|graph|echarts|watermark|context|inline-search|indexwrapper)/i;
const DECORATIVE_ATTR_RE = /(icon|logo|brand|avatar|badge|emoji|watermark|ima)/i;
const FILE_REFERENCE_RE = /\.(?:pdf|docx?|xlsx?|pptx?|png|jpe?g)\b/i;
const ATTRIBUTE_ALLOWLIST = {
  a: new Set(["href", "target", "rel", "title"]),
  img: new Set(["src", "alt", "title", "width", "height"]),
  td: new Set(["colspan", "rowspan", "headers"]),
  th: new Set(["colspan", "rowspan", "headers", "scope"]),
  ol: new Set(["start", "reversed"]),
  blockquote: new Set(["cite"]),
};

export const ANSWER_SURFACE_STYLE_TEXT = `
  :host {
    display: block;
    width: 100%;
    max-width: min(100%, 780px);
    color: var(--text, #111827);
  }

  * {
    box-sizing: border-box;
  }

  .answer-doc {
    color: var(--text, #111827);
    font: 400 15.5px/1.95 "Segoe UI Variable", "PingFang SC", "Microsoft YaHei", sans-serif;
    letter-spacing: -0.01em;
    word-break: break-word;
  }

  .answer-doc > :first-child {
    margin-top: 0 !important;
  }

  .answer-doc > :last-child {
    margin-bottom: 0 !important;
  }

  .answer-doc p,
  .answer-doc ul,
  .answer-doc ol,
  .answer-doc blockquote,
  .answer-doc pre,
  .answer-doc table,
  .answer-doc figure,
  .answer-doc hr,
  .answer-doc h1,
  .answer-doc h2,
  .answer-doc h3,
  .answer-doc h4,
  .answer-doc h5,
  .answer-doc h6 {
    margin: 0 0 16px;
  }

  .answer-doc h1,
  .answer-doc h2,
  .answer-doc h3,
  .answer-doc h4,
  .answer-doc h5,
  .answer-doc h6 {
    color: var(--text, #111827);
    font-weight: 700;
    line-height: 1.28;
    letter-spacing: -0.02em;
  }

  .answer-doc h1 {
    font-size: 1.72em;
  }

  .answer-doc h2 {
    font-size: 1.4em;
  }

  .answer-doc h3 {
    font-size: 1.18em;
  }

  .answer-doc ul,
  .answer-doc ol {
    padding-left: 1.3em;
  }

  .answer-doc li + li {
    margin-top: 4px;
  }

  .answer-doc blockquote {
    padding: 10px 16px;
    border-inline-start: 2px solid rgba(15, 23, 42, 0.14);
    border-radius: 0 16px 16px 0;
    background: rgba(255, 255, 255, 0.6);
    color: var(--muted-strong, #475569);
  }

  .answer-doc pre {
    padding: 14px 16px;
    border: 1px solid rgba(15, 23, 42, 0.08);
    border-radius: 16px;
    background: rgba(255, 255, 255, 0.82);
    overflow-x: auto;
    white-space: pre-wrap;
    word-break: break-word;
    box-shadow: 0 10px 24px rgba(15, 23, 42, 0.04);
  }

  .answer-doc code {
    font-family: "Cascadia Code", "SFMono-Regular", Consolas, monospace;
  }

  .answer-doc :not(pre) > code {
    padding: 0.12em 0.38em;
    border-radius: 8px;
    background: rgba(15, 23, 42, 0.06);
    font-size: 0.94em;
  }

  .answer-doc img {
    display: block;
    max-width: 100%;
    height: auto;
    margin: 18px 0;
    border-radius: 18px;
    background: rgba(255, 255, 255, 0.92);
    box-shadow: 0 18px 38px rgba(15, 23, 42, 0.08);
  }

  .answer-doc figure {
    display: grid;
    gap: 8px;
  }

  .answer-doc figcaption {
    color: var(--muted, #6b7280);
    font-size: 12px;
    line-height: 1.6;
  }

  .answer-doc table {
    width: 100%;
    border-collapse: separate;
    border-spacing: 0;
    overflow: hidden;
    border: 1px solid rgba(15, 23, 42, 0.08);
    border-radius: 16px;
    background: rgba(255, 255, 255, 0.84);
  }

  .answer-doc th,
  .answer-doc td {
    padding: 10px 12px;
    text-align: left;
    vertical-align: top;
  }

  .answer-doc thead th {
    color: var(--muted-strong, #475569);
    background: rgba(15, 23, 42, 0.04);
    border-bottom: 1px solid rgba(15, 23, 42, 0.08);
  }

  .answer-doc tbody tr:nth-child(even) {
    background: rgba(248, 250, 252, 0.78);
  }

  .answer-doc hr {
    border: 0;
    border-top: 1px solid rgba(15, 23, 42, 0.08);
  }

  .answer-doc a {
    color: #1d4ed8;
    text-decoration: underline;
    text-decoration-thickness: 1px;
    text-underline-offset: 3px;
  }

  .answer-doc svg,
  .answer-doc canvas,
  .answer-doc iframe,
  .answer-doc form,
  .answer-doc button,
  .answer-doc input,
  .answer-doc textarea,
  .answer-doc select {
    display: none !important;
  }

  @media (max-width: 720px) {
    .answer-doc {
      font-size: 15px;
      line-height: 1.88;
    }
  }
`;

export function normalizeWhitespace(value) {
  return String(value || "").replace(/\s+/g, " ").trim();
}

export function prepareAnswerRender(answerHtml) {
  const rawHtml = String(answerHtml || "").trim();
  if (!rawHtml) {
    return { contentHtml: "" };
  }

  const doc = toHtmlDocument(rawHtml);
  sanitizeAnswerDocument(doc);

  const hasContent = Boolean(
    normalizeWhitespace(doc.body?.textContent || "") ||
      doc.body?.querySelector(COMPLEX_CONTENT_SELECTOR),
  );

  return {
    contentHtml: hasContent ? serializeAnswerContent(doc) : "",
  };
}

export function textToRichHtml(value) {
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

export function setRichContent(node, html) {
  node.innerHTML = html;
}

export function renderTextRichContent(node, text, extraClass = "") {
  node.className = `message-rich rich-content${extraClass ? ` ${extraClass}` : ""}`;
  setRichContent(node, textToRichHtml(text));
}

function escapeHtml(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
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

function resolveHtmlUrl(value) {
  const normalized = String(value || "").trim();
  if (!normalized || BAD_PROTOCOL_RE.test(normalized)) {
    return "";
  }

  try {
    return new URL(normalized, HTML_BASE_URL).href;
  } catch (_) {
    return "";
  }
}

function isSafeHttpUrl(value) {
  return /^https?:\/\//i.test(String(value || "").trim());
}

function sanitizeAnswerDocument(doc) {
  doc.querySelectorAll("script,noscript,object,embed,iframe,style,link,meta,base,form,input,textarea,button,select,option,canvas,svg,header,footer,nav,aside,[id^='@context-ref'],[data-exposure-id*='inline-search'],[class*='ContextInlineIndex']").forEach((node) => node.remove());

  Array.from(doc.querySelectorAll("*")).forEach((element) => {
    if (!element.isConnected) {
      return;
    }

    if (isDecorativeMediaElement(element)) {
      element.remove();
      return;
    }

    sanitizeAttributes(element);
  });

  removeAuxiliaryNodes(doc.body);
  removeAnswerNoiseNodes(doc.body);
  unwrapLayoutNodes(doc.body);
  removeEmptyNodes(doc.body);
}

function sanitizeAttributes(element) {
  Array.from(element.attributes).forEach((attr) => {
    const name = attr.name.toLowerCase();
    if (name.startsWith("on")) {
      element.removeAttribute(attr.name);
    }
  });

  const tag = element.tagName.toLowerCase();
  if (tag === "a") {
    const href = resolveHtmlUrl(element.getAttribute("href") || "");
    if (!isSafeHttpUrl(href)) {
      element.replaceWith(...Array.from(element.childNodes));
      return;
    }
    element.setAttribute("href", href);
    element.setAttribute("target", "_blank");
    element.setAttribute("rel", "noreferrer");
  }

  if (tag === "img") {
    const src = resolveHtmlUrl(element.getAttribute("src") || "");
    if (!isSafeHttpUrl(src)) {
      element.remove();
      return;
    }
    element.setAttribute("src", src);
    element.setAttribute("loading", "lazy");
    if (!element.getAttribute("alt")) {
      element.setAttribute("alt", "");
    }
  }

  Array.from(element.attributes).forEach((attr) => {
    const name = attr.name.toLowerCase();
    if (name === "loading") {
      return;
    }
    const allowed = ATTRIBUTE_ALLOWLIST[tag];
    if (!allowed || !allowed.has(name)) {
      element.removeAttribute(attr.name);
    }
  });
}

function removeAuxiliaryNodes(root) {
  if (!root) {
    return;
  }

  Array.from(root.querySelectorAll(REMOVABLE_SELECTOR)).forEach((node) => {
    if (!node.isConnected) {
      return;
    }
    const text = normalizeWhitespace(node.textContent || "");
    const attrs = normalizeWhitespace(
      `${node.className || ""} ${node.id || ""} ${node.getAttribute("data-testid") || ""} ${node.getAttribute("data-role") || ""} ${node.getAttribute("aria-label") || ""}`,
    );
    if (!text && !node.querySelector(COMPLEX_CONTENT_SELECTOR)) {
      node.remove();
      return;
    }
    if (BRAND_TEXT_PATTERNS.some((pattern) => pattern.test(text)) && text.length <= 40) {
      node.remove();
      return;
    }
    if (looksLikeFileReferenceBlock(node, text)) {
      node.remove();
      return;
    }
    if (AUXILIARY_ATTR_RE.test(attrs) && text.length <= 400) {
      node.remove();
      return;
    }
    if (AUXILIARY_TEXT_PATTERNS.some((pattern) => pattern.test(text)) && text.length <= 240) {
      node.remove();
    }
  });

  Array.from(root.querySelectorAll("a,button")).forEach((node) => {
    const text = normalizeWhitespace(node.textContent || "");
    if (!text) {
      return;
    }
    if (AUXILIARY_TEXT_PATTERNS.some((pattern) => pattern.test(text)) && text.length <= 48) {
      node.remove();
    }
  });
}

function removeAnswerNoiseNodes(root) {
  if (!root) {
    return;
  }

  Array.from(root.querySelectorAll(REMOVABLE_SELECTOR)).forEach((node) => {
    if (!node.isConnected) {
      return;
    }
    if (node.querySelector(COMPLEX_CONTENT_SELECTOR)) {
      return;
    }
    const text = normalizeWhitespace(node.textContent || "");
    if (isAnswerNoiseText(text)) {
      node.remove();
    }
  });
}

function unwrapLayoutNodes(root) {
  if (!root) {
    return;
  }

  Array.from(root.querySelectorAll(LAYOUT_WRAPPER_SELECTOR)).forEach((node) => {
    if (!node.isConnected || node === root || node.attributes.length > 0) {
      return;
    }

    const ownText = normalizeWhitespace(
      Array.from(node.childNodes)
        .filter((child) => child.nodeType === Node.TEXT_NODE)
        .map((child) => child.textContent || "")
        .join(" "),
    );
    if (ownText || node.children.length !== 1) {
      return;
    }

    node.replaceWith(...Array.from(node.childNodes));
  });
}

function removeEmptyNodes(root) {
  if (!root) {
    return;
  }

  Array.from(root.querySelectorAll(REMOVABLE_SELECTOR)).forEach((node) => {
    if (!node.isConnected || node.querySelector(COMPLEX_CONTENT_SELECTOR)) {
      return;
    }
    if (!normalizeWhitespace(node.textContent || "")) {
      node.remove();
    }
  });
}

function isAnswerNoiseText(text) {
  const normalized = normalizeWhitespace(text);
  if (!normalized || normalized.length > 72) {
    return false;
  }
  return NOISE_TEXT_PATTERNS.some((pattern) => pattern.test(normalized));
}

function isDecorativeMediaElement(element) {
  const tag = element.tagName.toLowerCase();
  if (tag === "svg" || tag === "canvas") {
    return true;
  }
  if (tag !== "img") {
    return false;
  }

  const attrs = normalizeWhitespace(
    `${element.className || ""} ${element.id || ""} ${element.getAttribute("alt") || ""} ${element.getAttribute("aria-label") || ""} ${element.getAttribute("title") || ""} ${element.getAttribute("src") || ""}`,
  );
  if (DECORATIVE_ATTR_RE.test(attrs)) {
    return true;
  }

  const width = parseNumericAttribute(element.getAttribute("width"));
  const height = parseNumericAttribute(element.getAttribute("height"));
  const alt = normalizeWhitespace(element.getAttribute("alt") || "");
  if ((width > 0 && width <= 48) || (height > 0 && height <= 48)) {
    return !alt || alt.length <= 12;
  }
  return false;
}

function parseNumericAttribute(value) {
  const match = String(value || "").match(/\d+(?:\.\d+)?/);
  return match ? Number.parseFloat(match[0]) : 0;
}

function looksLikeFileReferenceBlock(node, text) {
  const normalized = normalizeWhitespace(text);
  if (!normalized) {
    return false;
  }

  const fileHits = (normalized.match(new RegExp(FILE_REFERENCE_RE.source, "gi")) || []).length;
  if (fileHits >= 2 && node.querySelectorAll("li").length >= 2) {
    return true;
  }

  if (fileHits === 0) {
    return false;
  }

  const segments = normalized.split(/\s+(?=\d+\.)/);
  const fileLikeSegments = segments.filter((segment) => FILE_REFERENCE_RE.test(segment)).length;
  return fileLikeSegments >= 3;
}

function serializeAnswerContent(doc) {
  return (doc.body?.innerHTML || "").trim();
}
