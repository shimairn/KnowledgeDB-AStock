from __future__ import annotations

import re
import time

from playwright.sync_api import Browser, Locator, Page

from ima_bridge.config import Settings
from ima_bridge.errors import AskTimeoutError, ConfigMismatchError, KBNotFoundError, LoginRequiredError
from ima_bridge.probes import APP_COMPOSER_SELECTORS, CONTENT_PREFIX, LOGIN_HINTS, LOADING_HINTS
from ima_bridge.utils import incremental_text, timestamp_slug

EXTENSION_PATTERN = re.compile(r"^chrome-extension://([a-z]{32})(?:/.*)?$")


class CdpAskDriver:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def ask(self, browser: Browser, question: str) -> tuple[str, str, list[str], str | None]:
        page = self._acquire_page(browser)
        self._ensure_login(page)
        self._ensure_target_kb(page)
        self._ensure_mode_model(page)

        before_text = self._body_text(page)
        before_html = self._body_html(page)
        self._submit_question(page, question)
        after_text, after_html = self._wait_answer(page, before_text)

        answer_text = incremental_text(before_text, after_text, question)
        if not answer_text:
            answer_text = after_text.strip()

        answer_html = after_html if after_html != before_html else ""
        references = self._extract_references(answer_text)
        screenshot = self._capture(page) if self.settings.capture_screenshot else None
        return answer_text, answer_html, references, screenshot

    def _acquire_page(self, browser: Browser) -> Page:
        pages = [page for context in browser.contexts for page in context.pages]
        for page in pages:
            url = page.url or ""
            if "knowledge-base.html" in url or "chat.html" in url:
                return page

        extension_id = self._discover_extension_id(pages)
        if extension_id:
            if not browser.contexts:
                raise KBNotFoundError("No browser context found after CDP connection")
            page = browser.contexts[0].new_page()
            page.goto(f"chrome-extension://{extension_id}/knowledge-base.html", wait_until="domcontentloaded")
            return page

        if pages:
            return pages[0]
        if not browser.contexts:
            raise KBNotFoundError("No page found in managed app instance")
        return browser.contexts[0].new_page()

    def _discover_extension_id(self, pages: list[Page]) -> str | None:
        for page in pages:
            match = EXTENSION_PATTERN.match(page.url or "")
            if match:
                return match.group(1)
        return None

    def _ensure_login(self, page: Page) -> None:
        text = self._body_text(page)
        if any(hint in text for hint in LOGIN_HINTS):
            raise LoginRequiredError("Managed app profile requires one-time login in ima app")

    def _ensure_target_kb(self, page: Page) -> None:
        if self._has_target_signals(page):
            return

        locator = page.get_by_text(self.settings.kb_title, exact=False)
        if locator.count() > 0:
            locator.first.click(timeout=1500)
            page.wait_for_timeout(800)

        if not self._has_target_signals(page):
            raise KBNotFoundError(
                f"Target knowledge base not confirmed: name={self.settings.kb_name}, owner={self.settings.kb_owner}, title={self.settings.kb_title}"
            )

    def _has_target_signals(self, page: Page) -> bool:
        text = self._body_text(page)
        return self.settings.kb_owner in text and self.settings.kb_title in text and CONTENT_PREFIX in text

    def _ensure_mode_model(self, page: Page) -> None:
        text = self._body_text(page)
        if self.settings.mode_name in text:
            return
        if self._find_composer(page) is not None:
            return
        raise ConfigMismatchError(f"Expected mode not visible: {self.settings.mode_name}")

    def _submit_question(self, page: Page, question: str) -> None:
        if not question.strip():
            raise AskTimeoutError("Question must not be empty")

        composer = self._find_composer(page)
        if composer is None:
            raise AskTimeoutError("Input composer not found")

        composer.click(timeout=1500)
        try:
            composer.fill("")
            composer.fill(question)
        except Exception:
            composer.click()
            page.keyboard.press("Control+A")
            page.keyboard.press("Backspace")
            page.keyboard.type(question)

        composer.press("Enter")
        page.wait_for_timeout(250)

    def _find_composer(self, page: Page) -> Locator | None:
        for selector in APP_COMPOSER_SELECTORS:
            locator = page.locator(selector)
            count = locator.count()
            for index in range(count):
                candidate = locator.nth(index)
                if candidate.is_visible():
                    return candidate
        return None

    def _wait_answer(self, page: Page, before_text: str) -> tuple[str, str]:
        deadline = time.monotonic() + self.settings.ask_timeout_seconds
        stable_rounds = 0
        previous_length = len(before_text)
        latest_text = before_text
        latest_html = self._body_html(page)

        while time.monotonic() < deadline:
            latest_text = self._body_text(page)
            latest_html = self._body_html(page)
            current_length = len(latest_text)
            grew = current_length > len(before_text)

            if current_length == previous_length:
                stable_rounds += 1
            else:
                stable_rounds = 0
            previous_length = current_length

            if grew and stable_rounds >= 2 and not self._has_loading_state(latest_text):
                return latest_text, latest_html

            page.wait_for_timeout(int(self.settings.poll_interval_seconds * 1000))

        raise AskTimeoutError("Timed out waiting for answer completion")

    def _has_loading_state(self, text: str) -> bool:
        return any(hint in text for hint in LOADING_HINTS)

    def _extract_references(self, answer_text: str) -> list[str]:
        references = []
        for line in answer_text.splitlines():
            line_text = line.strip()
            if not line_text:
                continue
            if line_text.startswith("[") and "]" in line_text:
                references.append(line_text)
        return references

    def _capture(self, page: Page) -> str:
        filename = f"{timestamp_slug()}.png"
        screenshot_path = self.settings.screenshots_dir / filename
        page.screenshot(path=str(screenshot_path), full_page=True)
        return str(screenshot_path.resolve())

    def _body_text(self, page: Page) -> str:
        return page.inner_text("body").strip()

    def _body_html(self, page: Page) -> str:
        return page.inner_html("body")
