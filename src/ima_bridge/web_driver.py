from __future__ import annotations

import time
from typing import Callable

from playwright.sync_api import BrowserContext, Page, Playwright

from ima_bridge._web.answer_extractor import WebAnswerExtractor
from ima_bridge._web.conversation import WebConversationRunner
from ima_bridge._web.knowledge_base import WebKnowledgeBaseNavigator
from ima_bridge._web.session import WebSession
from ima_bridge.config import Settings
from ima_bridge.driver_protocol import DriverAskResult, DriverModelCatalog
from ima_bridge.errors import AskTimeoutError
from ima_bridge.probes import GENERIC_TARGET_URL_PATHS
from ima_bridge.target_state import TargetStateStore


class WebAskDriver:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.session = WebSession(settings)
        self.target_store = TargetStateStore(
            path=settings.target_url_state_path,
            base_url=settings.web_base_url,
            generic_paths=GENERIC_TARGET_URL_PATHS,
        )
        self.answer_extractor = WebAnswerExtractor(settings=settings, session=self.session)
        self.kb_navigator = WebKnowledgeBaseNavigator(
            settings=settings,
            session=self.session,
            store=self.target_store,
        )
        self.conversation = WebConversationRunner(
            settings=settings,
            session=self.session,
            extractor=self.answer_extractor,
        )

    def health(self, playwright: Playwright, headless: bool) -> tuple[bool, str | None, str | None]:
        context = self.session.launch_context(playwright, headless=headless)
        try:
            page = self.session.acquire_page(context)
            if self.kb_navigator.try_open_remembered_target(page):
                return True, None, None

            self.session.open_home(page)
            text = self.session.body_text(page)
            if self.kb_navigator.is_login_required(text):
                return False, "LOGIN_REQUIRED", "Web profile requires login. Run `python -m ima_bridge login` once."
            if self.kb_navigator.confirm_target_context(page):
                return True, None, None

            self.kb_navigator.open_kb_hub(page)
            text = self.session.body_text(page)
            if self.kb_navigator.is_login_required(text):
                return False, "LOGIN_REQUIRED", "Web profile requires login. Run `python -m ima_bridge login` once."
            if self.kb_navigator.confirm_target_context(page) or self.kb_navigator.probe_target_entries(page):
                return True, None, None
            return (
                False,
                "KB_NOT_FOUND",
                f"Target knowledge base not confirmed: name={self.settings.kb_name}, owner={self.settings.kb_owner}, title={self.settings.kb_title}",
            )
        finally:
            context.close()

    def login(self, playwright: Playwright, timeout_seconds: float) -> tuple[bool, str | None, str | None]:
        context = self.session.launch_context(playwright, headless=False)
        try:
            page = self.session.acquire_page(context)
            self.session.open_home(page)
            if self.kb_navigator.try_open_remembered_target(page):
                return True, None, None

            deadline = time.monotonic() + timeout_seconds
            while time.monotonic() < deadline:
                target_page = self.kb_navigator.find_target_page(self.session.active_pages(context))
                if target_page is not None:
                    self.kb_navigator.remember_target_url(target_page)
                    return True, None, None
                self.session.wait_for_page_activity(context, 1000)
            return False, "LOGIN_REQUIRED", "Login timeout. Scan QR and open target knowledge base, then retry."
        finally:
            context.close()

    def discover_model_catalog(self, playwright: Playwright, headless: bool) -> DriverModelCatalog:
        context = self.session.launch_context(playwright, headless=headless)
        try:
            page = self._prepare_chat_page(context)
            return self.conversation.discover_model_catalog(page, preferred_model=self.settings.model_prefix, strict=False)
        finally:
            context.close()

    def ask(
        self,
        playwright: Playwright,
        question: str,
        headless: bool,
        model: str | None = None,
    ) -> DriverAskResult:
        return self._ask_impl(playwright=playwright, question=question, headless=headless, model=model, on_update=None)

    def ask_stream(
        self,
        playwright: Playwright,
        question: str,
        headless: bool,
        model: str | None,
        on_update: Callable[..., None],
    ) -> DriverAskResult:
        return self._ask_impl(playwright=playwright, question=question, headless=headless, model=model, on_update=on_update)

    def _ask_impl(
        self,
        playwright: Playwright,
        question: str,
        headless: bool,
        model: str | None,
        on_update: Callable[..., None] | None,
    ) -> DriverAskResult:
        context = self.session.launch_context(playwright, headless=headless)
        try:
            page = self._prepare_chat_page(context)
            self.conversation.start_new_conversation(page)
            selected_model = self.conversation.ensure_selected_model(page, requested_model=model)

            before_text = self.session.body_text(page)
            before_html = self.session.body_html(page)
            self.conversation.submit_question(page, question)
            after_text, after_html = self.conversation.wait_answer(
                page,
                before_text,
                question=question,
                on_update=on_update,
            )

            latest_block = self.answer_extractor.extract_latest_ai_block(page)
            if latest_block is not None:
                answer_text, answer_html, thinking_text = latest_block
            else:
                answer_text = self.answer_extractor.extract_answer_text(before_text, after_text, question)
                if not answer_text:
                    raise AskTimeoutError("Answer text not detected after completion")
                answer_html = after_html if after_html != before_html else ""
                thinking_text = self.answer_extractor.extract_latest_thinking_text(page)

            references = self.answer_extractor.extract_references(answer_text)
            screenshot = self.answer_extractor.capture(page) if self.settings.capture_screenshot else None
            return DriverAskResult(
                source_driver="web",
                model=selected_model,
                thinking_text=thinking_text,
                answer_text=answer_text,
                answer_html=answer_html,
                references=references,
                screenshot_path=screenshot,
            )
        finally:
            context.close()

    def _prepare_chat_page(self, context: BrowserContext) -> Page:
        page = self.session.acquire_page(context)
        self.session.open_home(page)
        self.kb_navigator.ensure_login(page)
        if not self.kb_navigator.try_open_remembered_target(page):
            self.kb_navigator.ensure_target_kb(page)
        target_page = self.kb_navigator.find_target_page(self.session.active_pages(context))
        if target_page is not None:
            page = target_page
        self.conversation.ensure_mode_model(page)
        return page
