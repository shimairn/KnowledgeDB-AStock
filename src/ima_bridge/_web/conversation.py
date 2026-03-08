from __future__ import annotations

import time
from typing import Callable

from playwright.sync_api import Locator, Page

from ima_bridge.config import Settings
from ima_bridge.errors import AskTimeoutError, ConfigMismatchError
from ima_bridge.probes import COMPOSER_SELECTORS, LOADING_HINTS, SEND_CONTROL_SELECTORS

from .answer_extractor import WebAnswerExtractor
from .session import WebSession


class WebConversationRunner:
    def __init__(self, settings: Settings, session: WebSession, extractor: WebAnswerExtractor) -> None:
        self.settings = settings
        self.session = session
        self.extractor = extractor

    def ensure_mode_model(self, page: Page) -> None:
        text = self.session.body_text(page)
        if self.settings.mode_name not in text:
            raise ConfigMismatchError(f"Expected mode not visible: {self.settings.mode_name}")
        if self.settings.model_prefix not in text:
            raise ConfigMismatchError(f"Expected model prefix not visible: {self.settings.model_prefix}")

    def submit_question(self, page: Page, question: str) -> None:
        if not question.strip():
            raise AskTimeoutError("Question must not be empty")

        composer = self.find_composer(page)
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

        is_contenteditable = (composer.get_attribute("contenteditable") or "").lower() == "true"
        if is_contenteditable:
            if not self.click_send_control(page):
                composer.press("Enter")
        else:
            composer.press("Enter")
            self.click_send_control(page)
        page.wait_for_timeout(300)

    def click_send_control(self, page: Page) -> bool:
        for selector in SEND_CONTROL_SELECTORS:
            locator = page.locator(selector)
            if self._click_locator_candidates(page, locator, max_candidates=3):
                return True
        return False

    def find_composer(self, page: Page) -> Locator | None:
        for selector in COMPOSER_SELECTORS:
            locator = page.locator(selector)
            count = locator.count()
            for index in range(count):
                candidate = locator.nth(index)
                if candidate.is_visible():
                    return candidate
        return None

    def wait_answer(
        self,
        page: Page,
        before_text: str,
        question: str,
        on_update: Callable[[str, str], None] | None = None,
    ) -> tuple[str, str]:
        deadline = time.monotonic() + self.settings.ask_timeout_seconds
        stable_rounds = 0
        previous_signature = self.text_signature(before_text)
        changed = False
        latest_text = before_text
        latest_html = self.session.body_html(page)
        latest_stream_text = ""

        while time.monotonic() < deadline:
            latest_text = self.session.body_text(page)
            latest_html = self.session.body_html(page)
            current_signature = self.text_signature(latest_text)

            if current_signature == previous_signature:
                stable_rounds += 1
            else:
                stable_rounds = 0
            previous_signature = current_signature

            if latest_text != before_text:
                changed = True

            if on_update is not None:
                stream_text = self.extractor.extract_latest_ai_text(page)
                if not stream_text:
                    stream_text = self.extractor.extract_answer_text(before_text, latest_text, question)
                if stream_text and stream_text != latest_stream_text:
                    if stream_text.startswith(latest_stream_text):
                        delta = stream_text[len(latest_stream_text) :]
                    else:
                        delta = stream_text
                    if delta:
                        on_update(delta, stream_text)
                    latest_stream_text = stream_text

            if changed and latest_text != before_text and stable_rounds >= 2 and not self.has_loading_state(latest_text):
                return latest_text, latest_html

            page.wait_for_timeout(int(self.settings.poll_interval_seconds * 1000))

        raise AskTimeoutError("Timed out waiting for answer completion")

    def text_signature(self, body_text: str) -> tuple[int, str]:
        tail_size = 512
        return len(body_text), body_text[-tail_size:]

    def has_loading_state(self, body_text: str) -> bool:
        return any(hint in body_text for hint in LOADING_HINTS)

    def _click_locator_candidates(self, page: Page, locator: Locator, max_candidates: int = 8) -> bool:
        try:
            count = locator.count()
        except Exception:
            return False

        for index in range(min(count, max_candidates)):
            candidate = locator.nth(index)
            if self._click_with_fallback(page, candidate):
                return True
        return False

    def _click_with_fallback(self, page: Page, locator: Locator) -> bool:
        try:
            if not locator.is_visible():
                return False
        except Exception:
            pass

        attempts = (
            lambda: locator.click(timeout=1800),
            lambda: (locator.scroll_into_view_if_needed(timeout=1800), locator.click(timeout=1800)),
            lambda: locator.click(timeout=1800, force=True),
            lambda: locator.evaluate("(element) => element.click()"),
        )
        for attempt in attempts:
            try:
                attempt()
                return True
            except Exception:
                continue

        try:
            box = locator.bounding_box()
            if box is not None:
                page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                return True
        except Exception:
            pass
        return False
