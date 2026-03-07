from __future__ import annotations

import time
from pathlib import Path

from playwright.sync_api import BrowserContext, Error as PlaywrightError, Locator, Page, Playwright, TimeoutError

from ima_bridge.config import Settings
from ima_bridge.errors import AskTimeoutError, ConfigMismatchError, KBNotFoundError, LoginRequiredError
from ima_bridge.utils import incremental_text, timestamp_slug

CONTENT_PREFIX = "\u5185\u5bb9("
INPUT_HINT = "\u8f93\u5165#"
LOGIN_HINTS = (
    "\u626b\u7801",
    "\u5fae\u4fe1\u767b\u5f55",
    "\u767b\u5f55\u540e",
    "\u8bf7\u5148\u767b\u5f55",
)
LOADING_HINTS = (
    "\u601d\u8003\u4e2d",
    "\u751f\u6210\u4e2d",
    "\u56de\u7b54\u4e2d",
    "\u52a0\u8f7d\u4e2d",
)


class WebAskDriver:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def health(self, playwright: Playwright, headless: bool) -> tuple[bool, str | None, str | None]:
        context = self._launch_context(playwright, headless=headless)
        try:
            page = self._acquire_page(context)
            self._open_home(page)
            text = self._body_text(page)
            if self._is_login_required(text):
                return False, "LOGIN_REQUIRED", "Web profile requires login. Run `python -m ima_bridge login` once."
            return True, None, None
        finally:
            context.close()

    def login(self, playwright: Playwright, timeout_seconds: float) -> tuple[bool, str | None, str | None]:
        context = self._launch_context(playwright, headless=False)
        try:
            page = self._acquire_page(context)
            self._open_home(page)

            deadline = time.monotonic() + timeout_seconds
            while time.monotonic() < deadline:
                text = self._body_text(page)
                if self._has_target_signals(text):
                    return True, None, None
                page.wait_for_timeout(1000)
            return False, "LOGIN_REQUIRED", "Login timeout. Scan QR and open target knowledge base, then retry."
        finally:
            context.close()

    def ask(self, playwright: Playwright, question: str, headless: bool) -> tuple[str, str, list[str], str]:
        context = self._launch_context(playwright, headless=headless)
        try:
            page = self._acquire_page(context)
            self._open_home(page)
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
            screenshot = self._capture(page)
            return answer_text, answer_html, references, screenshot
        finally:
            context.close()

    def _launch_context(self, playwright: Playwright, headless: bool) -> BrowserContext:
        kwargs = {
            "user_data_dir": str(self.settings.web_profile_dir.resolve()),
            "headless": headless,
            "viewport": {"width": 1600, "height": 1000},
            "args": ["--disable-blink-features=AutomationControlled"],
        }
        if self.settings.web_channel:
            kwargs["channel"] = self.settings.web_channel

        try:
            return playwright.chromium.launch_persistent_context(**kwargs)
        except PlaywrightError:
            kwargs.pop("channel", None)
            return playwright.chromium.launch_persistent_context(**kwargs)

    def _acquire_page(self, context: BrowserContext) -> Page:
        if context.pages:
            return context.pages[0]
        return context.new_page()

    def _open_home(self, page: Page) -> None:
        page.set_default_timeout(int(self.settings.web_navigation_timeout_seconds * 1000))
        page.goto(self.settings.web_base_url, wait_until="domcontentloaded")
        page.wait_for_timeout(700)

    def _ensure_login(self, page: Page) -> None:
        text = self._body_text(page)
        if self._is_login_required(text):
            raise LoginRequiredError("Web profile requires login. Run `python -m ima_bridge login` once.")

    def _is_login_required(self, body_text: str) -> bool:
        return any(hint in body_text for hint in LOGIN_HINTS)

    def _ensure_target_kb(self, page: Page) -> None:
        text = self._body_text(page)
        if self._has_target_signals(text):
            return

        for probe in (self.settings.kb_title, self.settings.kb_name):
            locator = page.get_by_text(probe, exact=False)
            if locator.count() > 0:
                locator.first.click(timeout=2000)
                page.wait_for_timeout(900)
                if self._has_target_signals(self._body_text(page)):
                    return

        raise KBNotFoundError(
            f"Target knowledge base not confirmed: name={self.settings.kb_name}, owner={self.settings.kb_owner}, title={self.settings.kb_title}"
        )

    def _has_target_signals(self, body_text: str) -> bool:
        return self.settings.kb_owner in body_text and self.settings.kb_title in body_text and CONTENT_PREFIX in body_text

    def _ensure_mode_model(self, page: Page) -> None:
        text = self._body_text(page)
        if self.settings.mode_name not in text:
            raise ConfigMismatchError(f"Expected mode not visible: {self.settings.mode_name}")
        if self.settings.model_prefix not in text:
            raise ConfigMismatchError(f"Expected model prefix not visible: {self.settings.model_prefix}")

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
        page.wait_for_timeout(300)

    def _find_composer(self, page: Page) -> Locator | None:
        selectors = [
            "textarea[placeholder*='\u8f93\u5165#']",
            "textarea[placeholder*='\u8f93\u5165']",
            "textarea",
            "[contenteditable='true']",
        ]
        for selector in selectors:
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

    def _has_loading_state(self, body_text: str) -> bool:
        return any(hint in body_text for hint in LOADING_HINTS)

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
        try:
            return page.inner_text("body").strip()
        except TimeoutError:
            return ""

    def _body_html(self, page: Page) -> str:
        try:
            return page.inner_html("body")
        except TimeoutError:
            return ""

