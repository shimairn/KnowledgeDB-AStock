from __future__ import annotations

import re

from playwright.sync_api import Locator, Page

from ima_bridge.config import Settings
from ima_bridge.utils import incremental_text, timestamp_slug
from ima_bridge.probes import AI_BUBBLE_SELECTOR, AI_CONTAINER_SELECTORS

from .session import WebSession


class WebAnswerExtractor:
    def __init__(self, settings: Settings, session: WebSession) -> None:
        self.settings = settings
        self.session = session

    def extract_answer_text(self, before_text: str, after_text: str, question: str) -> str:
        delta = incremental_text(before_text, after_text, question)
        if delta:
            return self._normalize_answer_candidate(delta)

        candidate = after_text
        if question:
            question_index = candidate.rfind(question)
            if question_index != -1:
                candidate = candidate[question_index + len(question) :]

        return self._normalize_answer_candidate(candidate)

    def _normalize_answer_candidate(self, candidate: str) -> str:
        candidate = candidate.lstrip(" \n\r\t:：)")
        if candidate.startswith("ima"):
            candidate = candidate[3:].lstrip(" \n\r\t:：)")

        for marker in (f"\n\n\n\n\n{self.settings.mode_name}", "\n问答历史\n"):
            marker_index = candidate.find(marker)
            if marker_index != -1:
                candidate = candidate[:marker_index]
                break

        return candidate.strip()

    def extract_latest_ai_block(self, page: Page) -> tuple[str, str] | None:
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
                node = bubble if bubble.count() > 0 else container
                try:
                    raw_text = node.inner_text(timeout=1500).strip()
                    raw_html = self.compose_answer_html(page, node)
                except Exception:
                    continue

                text = self.clean_ai_text(raw_text)
                if not text:
                    continue
                return text, raw_html
        return None

    def extract_latest_ai_text(self, page: Page) -> str:
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
                node = bubble if bubble.count() > 0 else container
                try:
                    raw_text = node.inner_text(timeout=1200).strip()
                except Exception:
                    continue
                text = self.clean_ai_text(raw_text)
                if text:
                    return text
        return ""

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
        lines = [line.strip() for line in text.splitlines()]
        while lines and not lines[0]:
            lines.pop(0)
        if lines and lines[0].lower() == "ima":
            lines.pop(0)
        while lines and not lines[-1]:
            lines.pop()
        return "\n".join(lines).strip()

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
