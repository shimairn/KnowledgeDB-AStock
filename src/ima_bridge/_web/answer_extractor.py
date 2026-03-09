from __future__ import annotations

import re
from dataclasses import dataclass

from playwright.sync_api import Locator, Page

from ima_bridge.config import Settings
from ima_bridge.probes import AI_BUBBLE_SELECTOR, AI_CONTAINER_SELECTORS
from ima_bridge.utils import incremental_text, timestamp_slug

from .session import WebSession

THINKING_LABELS = ("思考过程", "思考中", "推理过程", "深度思考", "Thinking", "Reasoning")
THINKING_LABEL_RE = re.compile(r"^(?:思考过程|思考中|推理过程|深度思考|Thinking|Reasoning)\s*[:：-]?\s*", re.IGNORECASE)
ANSWER_LABEL_RE = re.compile(r"^(?:最终回答|回答|答复|Final Answer|Answer)\s*[:：-]\s*", re.IGNORECASE)
THINKING_TAG_RE = re.compile(r"<think>\s*(.*?)\s*</think>\s*(.*)", re.IGNORECASE | re.DOTALL)
THINKING_SPLIT_RE = re.compile(
    r"(?:思考过程|推理过程|深度思考|thinking|reasoning)\s*[:：-]?\s*(.+?)"
    r"(?:最终回答|回答|答复|final answer|answer)\s*[:：-]?\s*(.+)",
    re.IGNORECASE | re.DOTALL,
)
KB_EMPTY_ANSWER_HINTS = (
    "没有找到相关的知识库内容",
    "未找到相关的知识库内容",
    "没有找到相关知识库内容",
    "未找到相关知识库内容",
)


@dataclass(frozen=True)
class ThinkingSplit:
    matched: bool = False
    thinking_text: str = ""
    answer_text: str = ""


@dataclass(frozen=True)
class ExtractedAIContent:
    answer_text: str = ""
    answer_html: str = ""
    thinking_text: str = ""


class WebAnswerExtractor:
    def __init__(self, settings: Settings, session: WebSession) -> None:
        self.settings = settings
        self.session = session

    def extract_answer_text(self, before_text: str, after_text: str, question: str) -> str:
        delta = incremental_text(before_text, after_text, question)
        if delta:
            normalized = self._normalize_answer_candidate(delta)
            split = self.split_thinking_answer(normalized)
            if split.matched and split.answer_text:
                return split.answer_text
            return normalized

        candidate = after_text
        if question:
            question_index = candidate.rfind(question)
            if question_index != -1:
                candidate = candidate[question_index + len(question) :]

        normalized = self._normalize_answer_candidate(candidate)
        split = self.split_thinking_answer(normalized)
        if split.matched and split.answer_text:
            return split.answer_text
        return normalized

    def _normalize_answer_candidate(self, candidate: str) -> str:
        candidate = candidate.lstrip(" \n\r\t:锛?")
        if candidate.startswith("ima"):
            candidate = candidate[3:].lstrip(" \n\r\t:锛?")

        for marker in (f"\n\n\n\n\n{self.settings.mode_name}", "\n闂瓟鍘嗗彶\n"):
            marker_index = candidate.find(marker)
            if marker_index != -1:
                candidate = candidate[:marker_index]
                break

        candidate = ANSWER_LABEL_RE.sub("", candidate, count=1)
        return candidate.strip()

    def extract_latest_ai_block(self, page: Page) -> tuple[str, str, str] | None:
        content = self.extract_latest_ai_content(page)
        if content is None:
            return None
        return content.answer_text, content.answer_html, content.thinking_text

    def extract_latest_ai_text(self, page: Page) -> str:
        content = self.extract_latest_ai_content(page)
        return "" if content is None else content.answer_text

    def extract_latest_thinking_text(self, page: Page) -> str:
        content = self.extract_latest_ai_content(page)
        return "" if content is None else content.thinking_text

    def extract_latest_ai_content(self, page: Page) -> ExtractedAIContent | None:
        target = self.find_latest_ai_nodes(page)
        if target is None:
            return None

        container, node = target
        try:
            raw_text = node.inner_text(timeout=1500).strip()
            container_text = container.inner_text(timeout=1500).strip()
            raw_html = self.compose_answer_html(page, container)
        except Exception:
            return None

        dom_payload = self.extract_dom_segments(container)
        thinking_text = self.clean_thinking_text(dom_payload.thinking_text)
        dom_answer_candidate = self.clean_ai_text(dom_payload.answer_text or container_text)

        answer_candidate = self.clean_ai_text(raw_text)
        if not answer_candidate:
            answer_candidate = dom_answer_candidate
        else:
            answer_candidate = self._prefer_richer_answer_candidate(answer_candidate, dom_answer_candidate)

        if thinking_text:
            answer_candidate = self.remove_fragment(answer_candidate, thinking_text)

        split_source = answer_candidate or dom_answer_candidate or self.clean_ai_text(container_text)
        split = self.split_thinking_answer(split_source)
        if split.matched:
            if not thinking_text:
                thinking_text = split.thinking_text
            if split.answer_text:
                answer_candidate = split.answer_text

        answer_candidate = self._normalize_answer_candidate(answer_candidate)
        if not answer_candidate and dom_payload.answer_text:
            answer_candidate = self._normalize_answer_candidate(self.clean_ai_text(dom_payload.answer_text))
        elif dom_payload.answer_text:
            answer_candidate = self._prefer_richer_answer_candidate(
                answer_candidate,
                self._normalize_answer_candidate(self.clean_ai_text(dom_payload.answer_text)),
            )

        if not answer_candidate and not thinking_text:
            return None

        return ExtractedAIContent(
            answer_text=answer_candidate,
            answer_html=raw_html,
            thinking_text=thinking_text,
        )

    def find_latest_ai_nodes(self, page: Page) -> tuple[Locator, Locator] | None:
        for selector in AI_CONTAINER_SELECTORS:
            containers = page.locator(selector)
            try:
                count = containers.count()
            except Exception:
                continue
            if count == 0:
                continue

            for index in range(count - 1, -1, -1):
                container = containers.nth(index)
                try:
                    if not container.is_visible():
                        continue
                except Exception:
                    continue

                bubble = container.locator(AI_BUBBLE_SELECTOR).first
                try:
                    node = bubble if bubble.count() > 0 else container
                except Exception:
                    node = container
                return container, node
        return None

    def extract_dom_segments(self, container: Locator) -> ExtractedAIContent:
        script = r"""
        (element) => {
          const normalize = (value) => (value || '')
            .replace(/\u00a0/g, ' ')
            .replace(/\s+/g, ' ')
            .trim();
          const labelRe = /(思考过程|思考中|推理过程|深度思考|thinking|reasoning)/i;
          const attrRe = /(think|reason|analysis|thought)/i;
          const clone = element.cloneNode(true);
          const candidates = [];

          for (const item of Array.from(clone.querySelectorAll('*'))) {
            const text = normalize(item.innerText || item.textContent || '');
            if (!text || text.length < 2) {
              continue;
            }
            const attrs = normalize(`${item.className || ''} ${item.getAttribute('data-testid') || ''} ${item.getAttribute('data-role') || ''} ${item.getAttribute('aria-label') || ''}`);
            const isThinking = labelRe.test(text) || attrRe.test(attrs);
            if (!isThinking) {
              continue;
            }
            candidates.push(text);
            item.remove();
          }

          const deduped = [];
          const seen = new Set();
          for (const text of candidates) {
            if (!text || seen.has(text)) {
              continue;
            }
            seen.add(text);
            deduped.push(text);
          }

          return {
            answerText: normalize(clone.innerText || clone.textContent || ''),
            thinkingText: deduped.join('\n\n'),
          };
        }
        """
        try:
            payload = container.evaluate(script, timeout=1500)
        except Exception:
            return ExtractedAIContent()

        return ExtractedAIContent(
            answer_text=str(payload.get("answerText", "") or ""),
            thinking_text=str(payload.get("thinkingText", "") or ""),
        )

    def split_thinking_answer(self, text: str) -> ThinkingSplit:
        candidate = str(text or "").strip()
        if not candidate:
            return ThinkingSplit()

        tag_match = THINKING_TAG_RE.fullmatch(candidate)
        if tag_match:
            thinking_text = self.clean_thinking_text(tag_match.group(1))
            answer_text = self._normalize_answer_candidate(tag_match.group(2))
            if thinking_text or answer_text:
                return ThinkingSplit(matched=True, thinking_text=thinking_text, answer_text=answer_text)

        label_match = THINKING_SPLIT_RE.search(candidate)
        if label_match:
            thinking_text = self.clean_thinking_text(label_match.group(1))
            answer_text = self._normalize_answer_candidate(label_match.group(2))
            if thinking_text or answer_text:
                return ThinkingSplit(matched=True, thinking_text=thinking_text, answer_text=answer_text)

        return ThinkingSplit()

    def clean_thinking_text(self, text: str) -> str:
        if not text:
            return ""

        cleaned_lines: list[str] = []
        for raw_line in str(text).splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line.lower() == "ima":
                continue
            line = THINKING_LABEL_RE.sub("", line, count=1)
            if line in {"展开", "收起"}:
                continue
            cleaned_lines.append(line)
        return "\n".join(cleaned_lines).strip()

    def remove_fragment(self, text: str, fragment: str) -> str:
        source = str(text or "")
        target = str(fragment or "").strip()
        if not source or not target:
            return source.strip()
        if target in source:
            return source.replace(target, "", 1).strip()
        compact_source = re.sub(r"\s+", " ", source).strip()
        compact_target = re.sub(r"\s+", " ", target).strip()
        if compact_target and compact_target in compact_source:
            compact_source = compact_source.replace(compact_target, "", 1).strip()
            return compact_source
        return source.strip()

    def compose_answer_html(self, page: Page, node: Locator) -> str:
        try:
            payload = node.evaluate(
                """
                (element) => {
                  const clone = element.cloneNode(true);
                  const removeSelectors = [
                    "div[id^='section-anchor-']",
                    "div[class*='_bottom_']",
                    "div[class*='_divider_']",
                    ".t-popup",
                    ".t-trigger",
                    "[data-popup]",
                    "button",
                    "script",
                    "style",
                    "noscript",
                    "iframe",
                    "[role='button']:not([id^='@context-ref'])",
                  ];

                  for (const selector of removeSelectors) {
                    for (const item of Array.from(clone.querySelectorAll(selector))) {
                      item.remove();
                    }
                  }

                  for (const item of Array.from(clone.querySelectorAll('*'))) {
                    for (const attr of Array.from(item.attributes)) {
                      const name = attr.name.toLowerCase();
                      if (name.startsWith('on')) {
                        item.removeAttribute(attr.name);
                      }
                    }

                    if (item.hasAttribute('src')) {
                      try {
                        item.setAttribute('src', new URL(item.getAttribute('src'), document.baseURI).href);
                      } catch (_) {
                      }
                    }

                    if (item.hasAttribute('href')) {
                      try {
                        item.setAttribute('href', new URL(item.getAttribute('href'), document.baseURI).href);
                      } catch (_) {
                      }
                    }
                  }

                  const wrapper = document.createElement('div');
                  wrapper.appendChild(clone);
                  return {
                    html: wrapper.innerHTML.trim(),
                    baseUrl: document.baseURI,
                  };
                }
                """,
                timeout=1500,
            )
        except Exception:
            return ""

        content_html = str(payload.get("html", "")).strip()
        if not content_html:
            return ""

        base_url = str(payload.get("baseUrl", page.url or self.settings.web_base_url)).strip() or self.settings.web_base_url
        class_names = self.extract_class_names(content_html)
        stylesheet_links = self.collect_stylesheet_links(page)
        styles_text = self.collect_page_styles(page, class_names)
        head_parts = [
            '<meta charset="utf-8" />',
            f'<base href="{base_url}" />',
        ]
        for href in stylesheet_links:
            head_parts.append(f'<link rel="stylesheet" href="{href}" />')
        head_parts.append(
            "<style>"
            "html,body{margin:0;padding:0;background:#fff;color:#1e2a45;}"
            "body{font:14px/1.6 \"Segoe UI\",\"PingFang SC\",\"Microsoft YaHei\",sans-serif;}"
            "img,svg,canvas,video{max-width:100%;height:auto;}"
            "table{max-width:100%;}"
            "pre{white-space:pre-wrap;word-break:break-word;}"
            "a{color:inherit;}"
            "</style>"
        )
        if styles_text:
            head_parts.append(f"<style>{styles_text}</style>")
        return f"<!doctype html><html><head>{''.join(head_parts)}</head><body>{content_html}</body></html>"

    def collect_stylesheet_links(self, page: Page) -> list[str]:
        script = """
        () => Array.from(document.querySelectorAll('link[rel="stylesheet"]'))
          .map((item) => item.href || '')
          .map((item) => item.trim())
          .filter(Boolean)
        """
        try:
            values = page.evaluate(script)
        except Exception:
            return []

        seen: set[str] = set()
        results: list[str] = []
        for value in values:
            href = str(value).strip()
            if not href or href in seen:
                continue
            seen.add(href)
            results.append(href)
        return results

    def extract_class_names(self, html: str) -> list[str]:
        class_names: set[str] = set()
        for match in re.finditer(r'class=["\']([^"\']+)["\']', html):
            value = match.group(1).strip()
            if not value:
                continue
            for name in value.split():
                cleaned = name.strip()
                if cleaned:
                    class_names.add(cleaned)
        return sorted(class_names)

    def collect_page_styles(self, page: Page, class_names: list[str]) -> str:
        script = """
        (classNames) => {
          const chunks = [];
          const seen = new Set();
          const targetSelectors = new Set((classNames || []).map((name) => `.${name}`));
          const hasTargets = targetSelectors.size > 0;
          const matchSelector = (selectorText) => {
            if (!hasTargets) return true;
            const selector = selectorText || '';
            for (const target of targetSelectors) {
              if (selector.includes(target)) return true;
            }
            return false;
          };
          const push = (value) => {
            const text = (value || '').trim();
            if (!text || seen.has(text)) return;
            seen.add(text);
            chunks.push(text);
          };

          const collectRules = (rules) => {
            const local = [];
            for (const rule of Array.from(rules || [])) {
              try {
                if (rule.type === CSSRule.STYLE_RULE) {
                  if (matchSelector(rule.selectorText || '')) {
                    local.push(rule.cssText);
                  }
                  continue;
                }
                if (rule.type === CSSRule.MEDIA_RULE || rule.type === CSSRule.SUPPORTS_RULE) {
                  const inner = collectRules(rule.cssRules || []);
                  if (!inner) continue;
                  if (rule.type === CSSRule.MEDIA_RULE) {
                    local.push(`@media ${rule.conditionText}{${inner}}`);
                  } else {
                    local.push(`@supports ${rule.conditionText}{${inner}}`);
                  }
                  continue;
                }
                if (!hasTargets && rule.cssText) {
                  local.push(rule.cssText);
                }
              } catch (_) {
              }
            }
            return local.join('\\n');
          };

          for (const sheet of Array.from(document.styleSheets)) {
            try {
              if (!sheet.cssRules) continue;
              const css = collectRules(sheet.cssRules);
              push(css);
            } catch (_) {
            }
          }
          return chunks.join('\\n');
        }
        """
        try:
            return page.evaluate(script, class_names)
        except Exception:
            return ""

    def clean_ai_text(self, text: str) -> str:
        lines = [line.strip() for line in str(text or "").splitlines()]
        while lines and not lines[0]:
            lines.pop(0)
        if lines and lines[0].lower() == "ima":
            lines.pop(0)
        while lines and not lines[-1]:
            lines.pop()
        return "\n".join(lines).strip()

    def _prefer_richer_answer_candidate(self, primary: str, secondary: str) -> str:
        primary_text = str(primary or "").strip()
        secondary_text = str(secondary or "").strip()
        if not primary_text:
            return secondary_text
        if not secondary_text or secondary_text == primary_text:
            return primary_text
        if self._is_empty_kb_answer(primary_text) and not self._is_empty_kb_answer(secondary_text):
            return secondary_text
        if self._is_empty_kb_answer(primary_text) and len(secondary_text) > len(primary_text):
            return secondary_text
        if primary_text in secondary_text and len(secondary_text) >= len(primary_text) + 16:
            return secondary_text
        return primary_text

    def _is_empty_kb_answer(self, text: str) -> bool:
        normalized = str(text or "").strip()
        return any(hint in normalized for hint in KB_EMPTY_ANSWER_HINTS)

    def extract_references(self, answer_text: str) -> list[str]:
        references: list[str] = []
        for line in answer_text.splitlines():
            line_text = line.strip()
            if not line_text:
                continue
            if line_text.startswith("[") and "]" in line_text:
                references.append(line_text)
        return references

    def capture(self, page: Page) -> str:
        filename = f"{timestamp_slug()}.png"
        screenshot_path = self.settings.screenshots_dir / filename
        page.screenshot(path=str(screenshot_path), full_page=True)
        return str(screenshot_path.resolve())
