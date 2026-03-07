from __future__ import annotations

import time
from pathlib import Path
from urllib.parse import urlparse

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
    "\u6b63\u5728\u641c\u7d22\u77e5\u8bc6\u5e93\u8d44\u6599",
    "\u505c\u6b62\u56de\u7b54",
)
MIN_TARGET_SCORE = 4
GENERIC_URL_PATHS = {"", "/", "/wikis"}


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
            if self._try_open_remembered_target(page):
                return True, None, None

            deadline = time.monotonic() + timeout_seconds
            while time.monotonic() < deadline:
                target_page = self._find_target_page(context.pages)
                if target_page is not None:
                    self._remember_target_url(target_page)
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
            if not self._try_open_remembered_target(page):
                self._ensure_target_kb(page)
            target_page = self._find_target_page(context.pages)
            if target_page is not None:
                page = target_page
            self._ensure_mode_model(page)

            before_text = self._body_text(page)
            before_html = self._body_html(page)
            self._submit_question(page, question)
            after_text, after_html = self._wait_answer(page, before_text)

            latest_block = self._extract_latest_ai_block(page)
            if latest_block is not None:
                answer_text, answer_html = latest_block
            else:
                answer_text = self._extract_answer_text(before_text, after_text, question)
                if not answer_text:
                    raise AskTimeoutError("Answer text not detected after completion")
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
        if self._confirm_target_context(page):
            return

        self._open_kb_hub(page)
        if self._confirm_target_context(page):
            return
        if self._probe_target_entries(page):
            return

        for nav in ("\u6211\u7684\u77e5\u8bc6\u5e93", "\u6211\u52a0\u5165\u7684"):
            nav_locator = page.get_by_text(nav, exact=False)
            if self._click_locator_candidates(page, nav_locator):
                page.wait_for_timeout(700)
                if self._confirm_target_context(page):
                    return
                if self._probe_target_entries(page):
                    return

        raise KBNotFoundError(
            f"Target knowledge base not confirmed: name={self.settings.kb_name}, owner={self.settings.kb_owner}, title={self.settings.kb_title}"
        )

    def _open_kb_hub(self, page: Page) -> None:
        hub_url = self.settings.web_base_url.rstrip("/") + "/wikis"
        try:
            page.goto(hub_url, wait_until="domcontentloaded")
            page.wait_for_timeout(900)
        except Exception:
            return

    def _probe_target_entries(self, page: Page) -> bool:
        for probe in (self.settings.kb_title, self.settings.kb_name):
            locator = page.get_by_text(probe, exact=False)
            if not self._click_locator_candidates(page, locator):
                continue
            page.wait_for_timeout(900)
            if self._confirm_target_context(page):
                return True
        return False

    def _has_target_signals(self, body_text: str) -> bool:
        if self.settings.kb_title not in body_text:
            return False
        return self._target_score(body_text) >= MIN_TARGET_SCORE

    def _target_score(self, body_text: str) -> int:
        score = 0
        if self.settings.kb_title in body_text:
            score += 2
        if self.settings.kb_owner in body_text:
            score += 1
        if CONTENT_PREFIX in body_text:
            score += 2
        if INPUT_HINT in body_text:
            score += 1
        return score

    def _find_target_page(self, pages: list[Page]) -> Page | None:
        best_page: Page | None = None
        best_score = -1
        for candidate in pages:
            text = self._body_text(candidate)
            score = self._target_score(text)
            if score > best_score:
                best_score = score
                best_page = candidate
        if best_page is None:
            return None
        return best_page if best_score >= MIN_TARGET_SCORE else None

    def _confirm_target_context(self, page: Page) -> bool:
        body_text = self._body_text(page)
        if self._has_target_signals(body_text):
            self._remember_target_url(page, body_text)
            return True

        target_page = self._find_target_page(page.context.pages)
        if target_page is None:
            return False

        target_text = self._body_text(target_page)
        if not self._has_target_signals(target_text):
            return False

        self._remember_target_url(target_page, target_text)
        return True

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

        is_contenteditable = (composer.get_attribute("contenteditable") or "").lower() == "true"
        if is_contenteditable:
            if not self._click_send_control(page):
                composer.press("Enter")
        else:
            composer.press("Enter")
            self._click_send_control(page)
        page.wait_for_timeout(300)

    def _click_send_control(self, page: Page) -> bool:
        selectors = (
            "#chat-input-bar-id span.icon-send-enable-big",
            "#chat-input-bar-id span[class*='icon-send-enable']",
            "#chat-input-bar-id [class*='sendBtnWrap'] span",
            "#chat-input-bar-id [class*='sendBtnWrap']",
        )
        for selector in selectors:
            locator = page.locator(selector)
            if self._click_locator_candidates(page, locator, max_candidates=3):
                return True
        return False

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
        previous_signature = self._text_signature(before_text)
        changed = False
        latest_text = before_text
        latest_html = self._body_html(page)

        while time.monotonic() < deadline:
            latest_text = self._body_text(page)
            latest_html = self._body_html(page)
            current_signature = self._text_signature(latest_text)

            if current_signature == previous_signature:
                stable_rounds += 1
            else:
                stable_rounds = 0
            previous_signature = current_signature

            if latest_text != before_text:
                changed = True

            if changed and latest_text != before_text and stable_rounds >= 2 and not self._has_loading_state(latest_text):
                return latest_text, latest_html

            page.wait_for_timeout(int(self.settings.poll_interval_seconds * 1000))

        raise AskTimeoutError("Timed out waiting for answer completion")

    def _text_signature(self, body_text: str) -> tuple[int, str]:
        tail_size = 512
        return len(body_text), body_text[-tail_size:]

    def _extract_answer_text(self, before_text: str, after_text: str, question: str) -> str:
        delta = incremental_text(before_text, after_text, question)
        if delta:
            return delta

        candidate = after_text
        if question:
            question_index = candidate.rfind(question)
            if question_index != -1:
                candidate = candidate[question_index + len(question) :]

        candidate = candidate.lstrip(" \n\r\t:：")
        if candidate.startswith("ima"):
            candidate = candidate[3:].lstrip(" \n\r\t:：")

        for marker in (f"\n\n\n\n\n{self.settings.mode_name}", "\n问答历史\n"):
            marker_index = candidate.find(marker)
            if marker_index != -1:
                candidate = candidate[:marker_index]
                break

        return candidate.strip()

    def _extract_latest_ai_block(self, page: Page) -> tuple[str, str] | None:
        selectors = (
            "div[class*='normalModeAiBubbleWrapper'] div[class*='aiContainer']",
            "div[class*='aiContainer_']",
        )
        for selector in selectors:
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

                bubble = container.locator("div[class*='_bubble_']").first
                node = bubble if bubble.count() > 0 else container
                try:
                    raw_text = node.inner_text(timeout=1500).strip()
                    raw_html = node.inner_html(timeout=1500)
                except Exception:
                    continue

                text = self._clean_ai_text(raw_text)
                if not text:
                    continue
                return text, raw_html
        return None

    def _clean_ai_text(self, text: str) -> str:
        lines = [line.strip() for line in text.splitlines()]
        while lines and not lines[0]:
            lines.pop(0)
        if lines and lines[0].lower() == "ima":
            lines.pop(0)
        while lines and not lines[-1]:
            lines.pop()
        return "\n".join(lines).strip()

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

    def _try_open_remembered_target(self, page: Page) -> bool:
        remembered = self._load_remembered_target_url()
        if not remembered:
            return False
        try:
            page.goto(remembered, wait_until="domcontentloaded")
            page.wait_for_timeout(800)
        except Exception:
            return False

        if self._confirm_target_context(page):
            return True
        self._clear_remembered_target_url()
        return False

    def _load_remembered_target_url(self) -> str | None:
        path = self.settings.target_url_state_path
        if not path.exists():
            return None
        value = path.read_text(encoding="utf-8").strip()
        if not value.startswith("https://ima.qq.com/"):
            return None
        return value

    def _clear_remembered_target_url(self) -> None:
        path = self.settings.target_url_state_path
        if path.exists():
            path.unlink(missing_ok=True)

    def _remember_target_url(self, page: Page, body_text: str | None = None) -> None:
        url = (page.url or "").strip()
        if not url.startswith("https://ima.qq.com/"):
            return
        text = body_text if body_text is not None else self._body_text(page)
        if not self._can_persist_target_url(url, text):
            return
        self.settings.target_url_state_path.parent.mkdir(parents=True, exist_ok=True)
        self.settings.target_url_state_path.write_text(url, encoding="utf-8")

    def _can_persist_target_url(self, url: str, body_text: str) -> bool:
        parsed = urlparse(url)
        path = parsed.path.rstrip("/")
        if path in GENERIC_URL_PATHS:
            return False
        return self._has_target_signals(body_text)

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
