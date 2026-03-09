from __future__ import annotations

import time
from typing import Callable

from playwright.sync_api import Locator, Page

from ima_bridge.config import Settings
from ima_bridge.driver_protocol import DriverModelCatalog, DriverModelOption
from ima_bridge.errors import AskTimeoutError, ConfigMismatchError
from ima_bridge.probes import (
    COMPOSER_SELECTORS,
    LOADING_HINTS,
    MODEL_OPTION_DESC_SELECTOR,
    MODEL_MENU_SELECTORS,
    MODEL_OPTION_NAME_SELECTOR,
    MODEL_OPTION_SELECTED_HINT,
    MODEL_OPTION_SELECTOR,
    MODEL_TITLE_SELECTORS,
    MODEL_TRIGGER_SELECTORS,
    SEND_CONTROL_SELECTORS,
)

from .answer_extractor import ExtractedAIContent, WebAnswerExtractor
from .interactions import click_locator_candidates, click_with_fallback
from .session import WebSession

HISTORY_HEADER_LABEL = "\u95ee\u7b54\u5386\u53f2"


def normalize_model_text(text: str) -> str:
    normalized = str(text or "").casefold().strip()
    replacements = {
        "deepseek": "ds",
        "thinking": "t",
        "think": "t",
        "tencent": "",
        "hunyuan": "hy",
        "娣峰厓": "hy",
    }
    for source, target in replacements.items():
        normalized = normalized.replace(source, target)
    return "".join(ch for ch in normalized if ch.isalnum())


def match_model_option(target: str | None, options: list[DriverModelOption]) -> DriverModelOption | None:
    normalized_target = normalize_model_text(target or "")
    if not normalized_target:
        return next((option for option in options if option.selected), None)

    for option in options:
        if option.value == target or option.label == target:
            return option

    exact_match = next(
        (
            option
            for option in options
            if normalize_model_text(option.value or option.label) == normalized_target
        ),
        None,
    )
    if exact_match is not None:
        return exact_match

    for option in options:
        option_key = normalize_model_text(option.value or option.label)
        if option_key.startswith(normalized_target) or normalized_target.startswith(option_key):
            return option
    return None


class WebConversationRunner:
    def __init__(self, settings: Settings, session: WebSession, extractor: WebAnswerExtractor) -> None:
        self.settings = settings
        self.session = session
        self.extractor = extractor

    def ensure_mode_model(self, page: Page) -> None:
        text = self.session.body_text(page)
        if self.settings.mode_name in text:
            return
        if self.find_composer(page) is not None:
            return
        raise ConfigMismatchError(f"Expected mode not visible: {self.settings.mode_name}")

    def discover_model_catalog(
        self,
        page: Page,
        preferred_model: str | None = None,
        *,
        strict: bool = False,
    ) -> DriverModelCatalog:
        self.ensure_mode_model(page)

        current_model = self.current_model_label(page)
        trigger = self.find_model_trigger(page)
        if trigger is None:
            return self._fallback_catalog(current_model or preferred_model or "")

        if not click_with_fallback(page, trigger):
            return self._fallback_catalog(current_model or preferred_model or "")

        self._wait_for_model_menu_state(page, open_state=True, timeout_ms=600)
        options = self._collect_model_options(page)
        if not options:
            self._ensure_model_menu_closed(page)
            return self._fallback_catalog(current_model or preferred_model or "")

        selected_option = match_model_option(current_model, options)
        desired_option = match_model_option(preferred_model, options) if preferred_model else None

        if preferred_model and desired_option is None and strict:
            self._ensure_model_menu_closed(page)
            raise ConfigMismatchError(f"Requested model not available: {preferred_model}")

        if desired_option is not None and (selected_option is None or desired_option.value != selected_option.value):
            option_locator = self._find_model_option_locator(page, desired_option)
            if option_locator is None or not click_with_fallback(page, option_locator):
                self._ensure_model_menu_closed(page)
                if strict:
                    raise ConfigMismatchError(f"Requested model not available: {preferred_model}")
            else:
                self._ensure_model_menu_closed(page)
                selected_option = desired_option
                current_model = desired_option.label
                options = self._mark_selected_option(options, desired_option)

        self._ensure_model_menu_closed(page)

        if not current_model:
            selected_option = selected_option or next((option for option in options if option.selected), None)
            if selected_option is not None:
                current_model = selected_option.label

        return DriverModelCatalog(current_model=current_model, options=options)

    def ensure_selected_model(self, page: Page, requested_model: str | None = None) -> str:
        preferred_model = requested_model or self.settings.model_prefix
        catalog = self.discover_model_catalog(page, preferred_model=preferred_model, strict=bool(requested_model))
        return catalog.current_model or preferred_model or ""

    def start_new_conversation(self, page: Page) -> bool:
        action = self.find_new_conversation_action(page)
        if action is None:
            return False

        if not click_with_fallback(page, action):
            return False

        page.wait_for_timeout(420)
        return self.find_composer(page) is not None

    def find_new_conversation_action(self, page: Page) -> Locator | None:
        text_locators = (
            page.get_by_role("button", name="新建对话"),
            page.get_by_text("新建对话", exact=False),
            page.locator("button").filter(has_text="新建对话"),
            page.locator("[role='button']").filter(has_text="新建对话"),
        )
        for locator in text_locators:
            candidate = self._first_visible_locator(locator)
            if candidate is not None:
                return candidate

        history_header = self.find_history_header(page)
        if history_header is None:
            return None

        toolbar = history_header.locator("xpath=preceding-sibling::*[1]")
        for locator in (
            toolbar.locator("div[class*='iconWrap']"),
            toolbar.locator("button"),
            toolbar.locator("[role='button']"),
        ):
            candidate = self._first_visible_locator(locator)
            if candidate is not None:
                return candidate
        return None

    def submit_question(self, page: Page, question: str) -> None:
        if not question.strip():
            raise AskTimeoutError("Question must not be empty")

        self._ensure_model_menu_closed(page)
        composer = self.find_composer(page)
        if composer is None:
            raise AskTimeoutError("Input composer not found")

        if not click_with_fallback(page, composer):
            raise AskTimeoutError("Input composer not clickable")
        try:
            composer.fill("")
            composer.fill(question)
        except Exception:
            self._ensure_model_menu_closed(page)
            if not click_with_fallback(page, composer):
                raise AskTimeoutError("Input composer not clickable")
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
            if click_locator_candidates(page, locator, max_candidates=3):
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

    def find_history_header(self, page: Page) -> Locator | None:
        for selector in ("div[class*='historyHeader']", "div[class*='chatSidePanelHeader']"):
            locator = page.locator(selector)
            try:
                count = locator.count()
            except Exception:
                continue

            for index in range(count):
                candidate = locator.nth(index)
                try:
                    if candidate.is_visible() and HISTORY_HEADER_LABEL in self._safe_locator_text(candidate):
                        return candidate
                except Exception:
                    continue

        locator = page.get_by_text(HISTORY_HEADER_LABEL, exact=False)
        try:
            if locator.count() == 0:
                return None
            header = locator.first.locator("xpath=ancestor::div[contains(@class, 'chatSidePanelHeader')][1]")
            return header.first if header.count() > 0 else None
        except Exception:
            return None

    def find_model_trigger(self, page: Page) -> Locator | None:
        for selector in MODEL_TRIGGER_SELECTORS:
            locator = page.locator(selector)
            count = locator.count()
            for index in range(count):
                candidate = locator.nth(index)
                try:
                    if candidate.is_visible():
                        return candidate
                except Exception:
                    continue
        return None

    def current_model_label(self, page: Page) -> str:
        trigger = self.find_model_trigger(page)
        if trigger is None:
            return ""

        for selector in MODEL_TITLE_SELECTORS:
            text = self._first_visible_locator_text(trigger.locator(selector))
            if text:
                return text

        return self._first_line(self._safe_locator_text(trigger))

    def wait_answer(
        self,
        page: Page,
        before_text: str,
        question: str,
        on_update: Callable[..., None] | None = None,
    ) -> tuple[str, str]:
        deadline = time.monotonic() + self.settings.ask_timeout_seconds
        stable_rounds = 0
        previous_signature = self.text_signature(before_text)
        content_stable_rounds = 0
        previous_content_signature = self.content_signature(ExtractedAIContent())
        changed = False
        latest_text = before_text
        latest_html = self.session.body_html(page)
        latest_answer_html = ""
        latest_thinking_text = ""
        latest_content = ExtractedAIContent()

        while time.monotonic() < deadline:
            latest_text = self.session.body_text(page)
            latest_html = self.session.body_html(page)
            latest_content = self.extractor.extract_latest_ai_content(page) or ExtractedAIContent()
            current_signature = self.text_signature(latest_text)
            current_content_signature = self.content_signature(latest_content)

            if current_signature == previous_signature:
                stable_rounds += 1
            else:
                stable_rounds = 0
            previous_signature = current_signature

            if current_content_signature == previous_content_signature:
                content_stable_rounds += 1
            else:
                content_stable_rounds = 0
            previous_content_signature = current_content_signature

            if latest_text != before_text or self.has_answer_content(latest_content):
                changed = True

            if on_update is not None:
                latest_answer_html = self._emit_html_snapshot(
                    current_html=latest_content.answer_html,
                    previous_html=latest_answer_html,
                    on_update=on_update,
                )
                latest_thinking_text = self._emit_update(
                    phase="thinking",
                    current_text=latest_content.thinking_text,
                    previous_text=latest_thinking_text,
                    on_update=on_update,
                )

            if changed and latest_text != before_text and stable_rounds >= 2 and not self.has_loading_state(latest_text):
                return latest_text, latest_html

            if self.has_stable_answer_content(latest_content, stable_rounds=content_stable_rounds):
                return latest_text, latest_html

            page.wait_for_timeout(int(self.settings.poll_interval_seconds * 1000))

        if self.has_stable_answer_content(latest_content, stable_rounds=content_stable_rounds):
            return latest_text, latest_html

        raise AskTimeoutError("Timed out waiting for answer completion")

    def text_signature(self, body_text: str) -> tuple[int, str]:
        tail_size = 512
        return len(body_text), body_text[-tail_size:]

    def content_signature(self, content: ExtractedAIContent) -> tuple[str, str, str]:
        return (
            str(content.answer_text or "").strip(),
            str(content.answer_html or "").strip(),
            str(content.thinking_text or "").strip(),
        )

    def has_loading_state(self, body_text: str) -> bool:
        return any(hint in body_text for hint in LOADING_HINTS)

    def has_answer_content(self, content: ExtractedAIContent) -> bool:
        return bool(str(content.answer_text or "").strip() or str(content.answer_html or "").strip())

    def has_stable_answer_content(self, content: ExtractedAIContent, *, stable_rounds: int) -> bool:
        if stable_rounds < 1 or not self.has_answer_content(content):
            return False
        return not self.has_loading_state(str(content.answer_text or ""))

    def _emit_update(
        self,
        phase: str,
        current_text: str,
        previous_text: str,
        on_update: Callable[..., None],
    ) -> str:
        normalized = str(current_text or "")
        if not normalized or normalized == previous_text:
            return previous_text

        if normalized.startswith(previous_text):
            delta = normalized[len(previous_text) :]
        else:
            delta = normalized

        delta = str(delta or "")
        if delta:
            on_update(phase, delta, normalized)
        return normalized

    def _emit_html_snapshot(
        self,
        current_html: str,
        previous_html: str,
        on_update: Callable[..., None],
    ) -> str:
        normalized = str(current_html or "").strip()
        if not normalized or normalized == previous_html:
            return previous_html
        on_update({"phase": "answer_html", "html": normalized})
        return normalized

    def _collect_model_options(self, page: Page) -> list[DriverModelOption]:
        locator = page.locator(MODEL_OPTION_SELECTOR)
        options: list[DriverModelOption] = []
        try:
            count = locator.count()
        except Exception:
            return options

        for index in range(count):
            candidate = locator.nth(index)
            try:
                if not candidate.is_visible():
                    continue
            except Exception:
                continue

            label = self._first_visible_locator_text(candidate.locator(MODEL_OPTION_NAME_SELECTOR))
            if not label:
                label = self._first_line(self._safe_locator_text(candidate))
            if not label:
                continue

            description = self._first_visible_locator_text(candidate.locator(MODEL_OPTION_DESC_SELECTOR))
            class_name = (candidate.get_attribute("class") or "").casefold()
            selected = MODEL_OPTION_SELECTED_HINT.casefold() in class_name or "selected" in class_name
            options.append(
                DriverModelOption(
                    value=label,
                    label=label,
                    description=description,
                    selected=selected,
                )
            )

        deduped: list[DriverModelOption] = []
        seen: set[str] = set()
        for option in options:
            key = normalize_model_text(option.value or option.label)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(option)
        return deduped

    def _find_model_option_locator(self, page: Page, option: DriverModelOption) -> Locator | None:
        locator = page.locator(MODEL_OPTION_SELECTOR)
        try:
            count = locator.count()
        except Exception:
            return None

        target_key = normalize_model_text(option.value or option.label)
        for index in range(count):
            candidate = locator.nth(index)
            try:
                if not candidate.is_visible():
                    continue
            except Exception:
                continue

            label = self._first_visible_locator_text(candidate.locator(MODEL_OPTION_NAME_SELECTOR))
            if not label:
                label = self._first_line(self._safe_locator_text(candidate))
            if normalize_model_text(label) == target_key:
                return candidate
        return None

    def _mark_selected_option(
        self,
        options: list[DriverModelOption],
        selected_option: DriverModelOption,
    ) -> list[DriverModelOption]:
        target_key = normalize_model_text(selected_option.value or selected_option.label)
        return [
            DriverModelOption(
                value=option.value,
                label=option.label,
                description=option.description,
                selected=normalize_model_text(option.value or option.label) == target_key,
            )
            for option in options
        ]

    def _fallback_catalog(self, current_model: str) -> DriverModelCatalog:
        label = str(current_model or "").strip()
        options = [DriverModelOption(value=label, label=label, selected=True)] if label else []
        return DriverModelCatalog(current_model=label, options=options)

    def _close_model_menu(self, page: Page) -> None:
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass

    def _ensure_model_menu_closed(self, page: Page, timeout_ms: int = 1500) -> bool:
        if self._wait_for_model_menu_state(page, open_state=False, timeout_ms=120):
            return True

        self._close_model_menu(page)
        if self._wait_for_model_menu_state(page, open_state=False, timeout_ms=timeout_ms):
            return True

        try:
            page.mouse.click(8, 8)
        except Exception:
            pass
        page.wait_for_timeout(80)
        self._close_model_menu(page)
        return self._wait_for_model_menu_state(page, open_state=False, timeout_ms=timeout_ms)

    def _wait_for_model_menu_state(self, page: Page, open_state: bool, timeout_ms: int = 1000) -> bool:
        deadline = time.monotonic() + (timeout_ms / 1000)
        while time.monotonic() < deadline:
            if self._is_model_menu_open(page) == open_state:
                return True
            page.wait_for_timeout(50)
        return self._is_model_menu_open(page) == open_state

    def _is_model_menu_open(self, page: Page) -> bool:
        for selector in MODEL_MENU_SELECTORS:
            locator = page.locator(selector)
            try:
                count = locator.count()
            except Exception:
                continue

            for index in range(count):
                candidate = locator.nth(index)
                try:
                    if candidate.is_visible():
                        return True
                except Exception:
                    continue
        return False

    def _first_visible_locator_text(self, locator: Locator) -> str:
        try:
            count = locator.count()
        except Exception:
            return ""

        for index in range(count):
            candidate = locator.nth(index)
            try:
                if not candidate.is_visible():
                    continue
            except Exception:
                continue

            text = self._first_line(self._safe_locator_text(candidate))
            if text:
                return text
        return ""

    def _safe_locator_text(self, locator: Locator) -> str:
        try:
            return (locator.inner_text(timeout=800) or "").strip()
        except Exception:
            return ""

    @staticmethod
    def _first_line(text: str) -> str:
        for line in str(text or "").splitlines():
            normalized = line.strip()
            if normalized:
                return normalized
        return ""

    def _first_visible_locator(self, locator: Locator) -> Locator | None:
        try:
            count = locator.count()
        except Exception:
            return None

        for index in range(count):
            candidate = locator.nth(index)
            try:
                if candidate.is_visible():
                    return candidate
            except Exception:
                continue
        return None
