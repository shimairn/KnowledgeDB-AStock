from __future__ import annotations

import html
import re
from typing import Any

NOISE_TEXT_PATTERNS = (
    re.compile(
        r"^(?:\u627e\u5230|\u5171\u627e\u5230)\s*\d+\s*\u6761(?:\u76f8\u5173)?"
        r"(?:\u77e5\u8bc6\u5e93)?(?:\u5185\u5bb9|\u7ed3\u679c|\u8d44\u6599|\u6587\u6863|\u4fe1\u606f).*$"
    ),
    re.compile(
        r"^\u5728\u77e5\u8bc6\u5e93\u4e2d\u627e\u5230\s*\d+\s*\u6761(?:\u76f8\u5173)?"
        r"(?:\u77e5\u8bc6\u5e93)?(?:\u5185\u5bb9|\u7ed3\u679c|\u8d44\u6599|\u6587\u6863|\u4fe1\u606f).*$"
    ),
    re.compile(
        r"^\u5df2\u4e3a\u4f60\u627e\u5230\s*\d+\s*\u6761(?:\u76f8\u5173)?"
        r"(?:\u5185\u5bb9|\u7ed3\u679c|\u8d44\u6599|\u6587\u6863|\u4fe1\u606f)?.*$"
    ),
)
NOISE_BLOCK_TAGS = ("p", "div", "section", "article", "li", "span")
AUXILIARY_BLOCK_TAGS = (
    "div",
    "section",
    "article",
    "aside",
    "details",
    "summary",
    "ul",
    "ol",
    "li",
    "span",
    "figure",
    "header",
    "footer",
)
NOISE_BLOCK_RE = re.compile(
    rf"<(?P<tag>{'|'.join(NOISE_BLOCK_TAGS)})\b[^>]*>\s*(?P<inner>.*?)\s*</(?P=tag)>",
    re.IGNORECASE | re.DOTALL,
)
AUXILIARY_BLOCK_RE = re.compile(
    rf"<(?P<tag>{'|'.join(AUXILIARY_BLOCK_TAGS)})\b(?P<attrs>[^>]*)>\s*(?P<inner>.*?)\s*</(?P=tag)>",
    re.IGNORECASE | re.DOTALL,
)
LEADING_AUXILIARY_BLOCK_RE = re.compile(
    r"^\s*<(?P<tag>div|section|article)\b(?P<attrs>[^>]*)>\s*(?P<inner>.*?)\s*</(?P=tag)>\s*"
    r"(?=<(?:div|section|article)\b[^>]*(?:markdown|article|answer|content|rich)[^>]*>)",
    re.IGNORECASE | re.DOTALL,
)
THINK_TAG_RE = re.compile(r"<think\b[^>]*>.*?</think>", re.IGNORECASE | re.DOTALL)
INLINE_AUXILIARY_RE = re.compile(
    r"<(?:a|button)\b[^>]*>\s*(?:"
    r"\u6253\u5f00\u539f\u6587|"
    r"\u539f\u6587\u9884\u89c8|"
    r"\u5f15\u7528\u6765\u6e90|"
    r"\u6765\u6e90|"
    r"\u53c2\u8003\u8d44\u6599|"
    r"\u67e5\u770b\u6765\u6e90"
    r")\s*</(?:a|button)>",
    re.IGNORECASE,
)
DECORATIVE_MEDIA_RE = re.compile(r"<(?:svg|canvas)\b.*?</(?:svg|canvas)>", re.IGNORECASE | re.DOTALL)
DECORATIVE_IMG_RE = re.compile(
    r"<img\b(?=[^>]*(?:class|id|alt|aria-label|title)=['\"][^'\"]*"
    # NOTE: Do not match "ima" alone here. Many legitimate answer images include "ima" in
    # class/id/alt attributes, and stripping them results in large empty placeholders in the UI.
    r"(?:icon|logo|brand|avatar|badge|watermark)[^'\"]*['\"])[^>]*>",
    re.IGNORECASE,
)
INLINE_CONTEXT_REF_RE = re.compile(
    r"<(?:div|span)\b[^>]*(?:id=['\"]@context-ref[^'\"]*['\"]|data-exposure-id=['\"][^'\"]*inline-search[^'\"]*['\"]|class=['\"][^'\"]*ContextInlineIndex[^'\"]*['\"])[^>]*>.*?</(?:div|span)>",
    re.IGNORECASE | re.DOTALL,
)
COMPLEX_HTML_RE = re.compile(r"<(?:a|table|blockquote|pre|code|img|figure|ul|ol|dl)\b", re.IGNORECASE)
AUXILIARY_ATTR_RE = re.compile(
    r"(?:think|reason|analysis|thought|source|reference|citation|drawer|toolbar|menu|popover|tooltip|tab|legend|axis|chart|graph|echarts|watermark|context|inline-search|indexwrapper)",
    re.IGNORECASE,
)
AUXILIARY_TEXT_PATTERNS = (
    re.compile(r"^(?:\u601d\u8003\u8fc7\u7a0b|\u6df1\u5ea6\u601d\u8003|\u63a8\u7406\u8fc7\u7a0b|\u601d\u8003\u4e2d).*$"),
    re.compile(r"^(?:\u6765\u6e90|\u5f15\u7528\u6765\u6e90|\u53c2\u8003\u8d44\u6599|\u539f\u6587\u9884\u89c8|\u6253\u5f00\u539f\u6587|\u67e5\u770b\u6765\u6e90).*$"),
    re.compile(r"^(?:ima|tencent ima|\u817e\u8baf\s*ima)$", re.IGNORECASE),
)
TAG_RE = re.compile(r"<[^>]+>")
BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
WHITESPACE_RE = re.compile(r"\s+")
FILE_REFERENCE_RE = re.compile(r"\.(?:pdf|docx?|xlsx?|pptx?|png|jpe?g)\b", re.IGNORECASE)
LIST_ITEM_RE = re.compile(r"<li\b", re.IGNORECASE)
FILE_REFERENCE_CLUSTER_RE = re.compile(
    r"<(?:div|section|article)\b[^>]*>\s*"
    r"(?:<(?:div|section|article)\b[^>]*>\s*<li\b[^>]*>.*?\.(?:pdf|docx?|xlsx?|pptx?|png|jpe?g).*?</li>\s*</(?:div|section|article)>\s*){2,}"
    r"</(?:div|section|article)>",
    re.IGNORECASE | re.DOTALL,
)


def normalize_whitespace(value: str) -> str:
    return WHITESPACE_RE.sub(" ", str(value or "")).strip()


def is_answer_noise_text(text: str) -> bool:
    normalized = normalize_whitespace(text)
    if not normalized or len(normalized) > 72:
        return False
    return any(pattern.match(normalized) for pattern in NOISE_TEXT_PATTERNS)


def clean_answer_text(text: str) -> str:
    blocks: list[str] = []
    normalized_text = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    for raw_block in re.split(r"\n{2,}", normalized_text):
        kept_lines = []
        for raw_line in raw_block.split("\n"):
            line = raw_line.strip()
            if not line or is_answer_noise_text(line):
                continue
            if any(pattern.match(line) for pattern in AUXILIARY_TEXT_PATTERNS):
                continue
            kept_lines.append(line)
        if kept_lines:
            blocks.append("\n".join(kept_lines))
    return "\n\n".join(blocks).strip()


def clean_answer_html(answer_html: str) -> str:
    cleaned = str(answer_html or "").strip()
    if not cleaned:
        return ""

    cleaned = THINK_TAG_RE.sub("", cleaned)
    cleaned = INLINE_AUXILIARY_RE.sub("", cleaned)
    cleaned = DECORATIVE_MEDIA_RE.sub("", cleaned)
    cleaned = DECORATIVE_IMG_RE.sub("", cleaned)
    cleaned = INLINE_CONTEXT_REF_RE.sub("", cleaned)
    cleaned = FILE_REFERENCE_CLUSTER_RE.sub("", cleaned)

    previous = None
    while cleaned != previous:
        previous = cleaned
        cleaned = AUXILIARY_BLOCK_RE.sub(_replace_auxiliary_block, cleaned)
        cleaned = NOISE_BLOCK_RE.sub(_replace_noise_block, cleaned)
        cleaned = _strip_leading_auxiliary_blocks(cleaned)

    cleaned = INLINE_AUXILIARY_RE.sub("", cleaned)
    cleaned = DECORATIVE_MEDIA_RE.sub("", cleaned)
    cleaned = DECORATIVE_IMG_RE.sub("", cleaned)
    cleaned = INLINE_CONTEXT_REF_RE.sub("", cleaned)
    cleaned = FILE_REFERENCE_CLUSTER_RE.sub("", cleaned)
    cleaned = _strip_leading_auxiliary_blocks(cleaned)
    return cleaned.strip()


def clean_answer_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    data = dict(payload or {})
    data["answer_text"] = clean_answer_text(str(data.get("answer_text", "") or ""))
    data["answer_html"] = clean_answer_html(str(data.get("answer_html", "") or ""))
    return data


def _replace_noise_block(match: re.Match[str]) -> str:
    inner_html = match.group("inner") or ""
    if not inner_html.strip() or COMPLEX_HTML_RE.search(inner_html):
        return match.group(0)

    text = _strip_html_text(inner_html)
    if is_answer_noise_text(text):
        return ""
    return match.group(0)


def _replace_auxiliary_block(match: re.Match[str]) -> str:
    attrs = normalize_whitespace(match.group("attrs") or "")
    inner_html = match.group("inner") or ""
    if not inner_html.strip():
        return ""

    text = _strip_html_text(inner_html)
    if not text:
        return match.group(0) if COMPLEX_HTML_RE.search(inner_html) else ""
    if is_answer_noise_text(text):
        return ""
    if _looks_like_file_reference_block(inner_html, text):
        return ""
    if any(pattern.match(text) for pattern in AUXILIARY_TEXT_PATTERNS):
        return "" if len(text) <= 240 else match.group(0)
    if AUXILIARY_ATTR_RE.search(attrs):
        return "" if len(text) <= 400 else match.group(0)
    return match.group(0)


def _strip_leading_auxiliary_blocks(value: str) -> str:
    cleaned = str(value or "")
    while True:
        match = LEADING_AUXILIARY_BLOCK_RE.match(cleaned)
        if match is None:
            return cleaned

        inner_html = match.group("inner") or ""
        text = _strip_html_text(inner_html)
        if COMPLEX_HTML_RE.search(inner_html) or len(text) > 1200:
            return cleaned

        cleaned = cleaned[match.end() :].lstrip()


def _strip_html_text(value: str) -> str:
    text = BR_RE.sub("\n", str(value or ""))
    text = TAG_RE.sub(" ", text)
    return normalize_whitespace(html.unescape(text))


def _looks_like_file_reference_block(inner_html: str, text: str) -> bool:
    file_hits = len(FILE_REFERENCE_RE.findall(inner_html))
    if file_hits >= 2 and len(LIST_ITEM_RE.findall(inner_html)) >= 2:
        return True

    normalized = normalize_whitespace(text)
    if not normalized or file_hits == 0:
        return False

    segments = re.split(r"\s+(?=\d+\.)", normalized)
    file_like_segments = sum(1 for segment in segments if FILE_REFERENCE_RE.search(segment))
    return file_like_segments >= 3
