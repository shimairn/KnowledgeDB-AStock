from __future__ import annotations

import re
import time
from pathlib import Path

from playwright.sync_api import Locator, Page, TimeoutError as PlaywrightTimeoutError, sync_playwright

from ima_bridge.config import Settings
from ima_bridge.errors import AskTimeoutError, CaptureFailedError, ConfigMismatchError, KBNotFoundError, LoginRequiredError
from ima_bridge.schemas import AskResponse, DriverHealth, KnowledgeBaseIdentity, ReferenceItem
from ima_bridge.utils import ensure_parent, get_logger, timestamp_slug

from .base import AskDriver


class WebDriver(AskDriver):
    source_driver = "web_fallback"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.logger = get_logger("ima_bridge.web_driver")

    def health(self) -> DriverHealth:
        msedge = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
        available = msedge.exists()
        detail = f"msedge={'ok' if available else 'missing'}; profile={self.settings.browser_profile_dir}"
        return DriverHealth(name=self.source_driver, available=available, detail=detail)

    def ask(self, question: str) -> AskResponse:
        with sync_playwright() as playwright:
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=str(self.settings.browser_profile_dir),
                channel="msedge",
                headless=self.settings.headless,
                viewport={"width": 1600, "height": 1000},
            )
            try:
                page = context.pages[0] if context.pages else context.new_page()
                self._prepare_page(page)
                self._ensure_logged_in(page)
                self._open_target_knowledge_base(page)
                self._verify_kb_and_config(page)
                content_root = self._get_content_root(page)
                baseline_text = self._safe_text(content_root)
                editor = self._locate_editor(page)
                self._submit_question(page, editor, question)
                self._wait_for_answer_complete(page, content_root, baseline_text)
                return self._capture_result(page, content_root, question)
            finally:
                context.close()

    def _prepare_page(self, page: Page) -> None:
        page.set_default_timeout(10_000)
        page.set_default_navigation_timeout(20_000)

    def _ensure_logged_in(self, page: Page) -> None:
        page.goto(self.settings.web_wikis_url, wait_until="domcontentloaded")
        self._wait_for_settle(page)
        if self._is_login_state(page):
            self.logger.info("ima web requires login, waiting for manual scan")
            deadline = time.monotonic() + self.settings.login_wait_seconds
            while time.monotonic() < deadline:
                if not self._is_login_state(page):
                    self._wait_for_settle(page)
                    return
                time.sleep(1)
                try:
                    page.reload(wait_until="domcontentloaded")
                except PlaywrightTimeoutError:
                    pass
            raise LoginRequiredError("网页登录未完成，请在 Edge 中扫码登录 ima 后重试")

    def _open_target_knowledge_base(self, page: Page) -> None:
        if self._page_has_text(page, self.settings.kb_title):
            return
        page.goto(self.settings.web_wikis_url, wait_until="domcontentloaded")
        self._wait_for_settle(page)
        search_input = self._find_first_visible(page, [
            lambda p: p.get_by_placeholder(re.compile("搜索")),
            lambda p: p.locator("input[placeholder*='搜索']"),
            lambda p: p.locator("input[type='search']"),
            lambda p: p.locator("input"),
        ])
        if search_input is None:
            raise KBNotFoundError("未找到知识库搜索框，无法定位爱分享知识库")
        search_input.click()
        try:
            search_input.fill("")
        except Exception:
            pass
        search_input.fill(self.settings.kb_name)
        page.wait_for_timeout(1000)
        title_match = page.get_by_text(self.settings.kb_title, exact=False)
        if title_match.count() == 0:
            title_match = page.get_by_text(self.settings.kb_name, exact=False)
        if title_match.count() == 0:
            raise KBNotFoundError(f"未搜索到知识库: {self.settings.kb_title}")
        title_match.first.click()
        self._wait_for_settle(page)

    def _verify_kb_and_config(self, page: Page) -> None:
        if not self._page_has_text(page, self.settings.kb_title):
            raise KBNotFoundError(f"未进入目标知识库页面: {self.settings.kb_title}")
        if not self._page_has_text(page, self.settings.kb_owner):
            raise KBNotFoundError(f"未匹配到目标知识库 owner: {self.settings.kb_owner}")
        if not self._page_has_text(page, self.settings.mode):
            raise ConfigMismatchError(f"未检测到要求的模式: {self.settings.mode}")
        if not self._page_has_text(page, self.settings.model) and not self._page_has_text(page, "V3.2"):
            raise ConfigMismatchError(f"未检测到要求的模型: {self.settings.model}")

    def _locate_editor(self, page: Page) -> Locator:
        exact_placeholder = "输入#，可指定标签回答"
        candidates = [
            lambda p: p.get_by_placeholder(exact_placeholder),
            lambda p: p.locator("[placeholder*='标签回答']"),
            lambda p: p.locator("textarea"),
            lambda p: p.locator("[role='textbox']"),
            lambda p: p.locator("[contenteditable='true']"),
        ]
        locator = self._find_first_visible(page, candidates, prefer_last=True)
        if locator is None:
            raise CaptureFailedError("未找到提问输入框")
        return locator

    def _submit_question(self, page: Page, editor: Locator, question: str) -> None:
        editor.click()
        try:
            editor.fill("")
            editor.fill(question)
        except Exception:
            page.keyboard.press("Control+A")
            page.keyboard.press("Backspace")
            page.keyboard.insert_text(question)
        page.keyboard.press("Enter")
        page.wait_for_timeout(800)
        if self._editor_still_contains(editor, question):
            send_button = self._find_send_button(page, editor)
            if send_button is None:
                raise CaptureFailedError("问题已输入，但未能确认发送操作")
            send_button.click()

    def _wait_for_answer_complete(self, page: Page, content_root: Locator, baseline_text: str) -> None:
        deadline = time.monotonic() + self.settings.answer_timeout_seconds
        stable_polls = 0
        last_text = self._safe_text(content_root)
        baseline_len = len(baseline_text.strip())
        while time.monotonic() < deadline:
            page.wait_for_timeout(int(self.settings.answer_poll_seconds * 1000))
            current_text = self._safe_text(content_root)
            current_len = len(current_text.strip())
            loading = self._looks_like_loading(page)
            if current_len > baseline_len and current_text == last_text and not loading:
                stable_polls += 1
                if stable_polls >= 2:
                    return
            else:
                stable_polls = 0
            last_text = current_text
        raise AskTimeoutError("等待 ima 回答超时")

    def _capture_result(self, page: Page, content_root: Locator, question: str) -> AskResponse:
        html = self._safe_inner_html(content_root)
        text = self._safe_text(content_root)
        screenshot_path = ensure_parent(Path(self.settings.screenshot_dir) / f"web-answer-{timestamp_slug()}.png")
        try:
            content_root.screenshot(path=str(screenshot_path))
        except Exception:
            page.screenshot(path=str(screenshot_path), full_page=True)
        references = self._extract_references(content_root)
        return AskResponse(
            ok=True,
            question=question,
            knowledge_base=KnowledgeBaseIdentity(
                name=self.settings.kb_name,
                owner=self.settings.kb_owner,
                title=self.settings.kb_title,
            ),
            mode=self.settings.mode,
            model=self.settings.model,
            source_driver=self.source_driver,
            answer_text=text,
            answer_html=html,
            references=references,
            screenshot_path=str(screenshot_path.resolve()),
        )

    def _extract_references(self, root: Locator) -> list[ReferenceItem]:
        items: list[ReferenceItem] = []
        try:
            payload = root.locator("a").evaluate_all(
                "els => els.map(el => ({ text: (el.innerText || el.textContent || '').trim(), href: el.href || null })).filter(x => x.text || x.href)"
            )
            for item in payload[:20]:
                items.append(ReferenceItem(text=item.get("text") or "", href=item.get("href")))
        except Exception:
            return []
        return items

    def _find_send_button(self, page: Page, editor: Locator) -> Locator | None:
        try:
            editor_box = editor.bounding_box()
        except Exception:
            editor_box = None
        buttons = page.locator("button, [role='button']")
        count = min(buttons.count(), 50)
        best: tuple[float, Locator] | None = None
        for index in range(count):
            locator = buttons.nth(index)
            try:
                if not locator.is_visible():
                    continue
                box = locator.bounding_box()
                if not box:
                    continue
                score = box["x"]
                if editor_box and box["y"] < editor_box["y"] - 80:
                    continue
                if best is None or score > best[0]:
                    best = (score, locator)
            except Exception:
                continue
        return best[1] if best else None

    def _get_content_root(self, page: Page) -> Locator:
        for candidate in [page.locator("main"), page.locator("[role='main']"), page.locator("#root"), page.locator("body")]:
            try:
                if candidate.count() and candidate.first.is_visible():
                    return candidate.first
            except Exception:
                continue
        return page.locator("body")

    def _safe_text(self, locator: Locator) -> str:
        try:
            return locator.inner_text(timeout=10_000)
        except Exception:
            return ""

    def _safe_inner_html(self, locator: Locator) -> str:
        try:
            return locator.inner_html(timeout=10_000)
        except Exception:
            return ""

    def _editor_still_contains(self, editor: Locator, text: str) -> bool:
        for _ in range(3):
            try:
                value = editor.input_value(timeout=1000)
            except Exception:
                try:
                    value = editor.inner_text(timeout=1000)
                except Exception:
                    value = ""
            if text.strip() and text.strip() in value:
                return True
            time.sleep(0.2)
        return False

    def _is_login_state(self, page: Page) -> bool:
        url = page.url.lower()
        if "/login/" in url or "universal-login" in url:
            return True
        for marker in ["登录", "扫码", "微信登录"]:
            if self._page_has_text(page, marker):
                return True
        return False

    def _looks_like_loading(self, page: Page) -> bool:
        markers = ["思考中", "生成中", "回答中", "停止生成"]
        return any(self._page_has_text(page, marker) for marker in markers)

    def _page_has_text(self, page: Page, text: str) -> bool:
        try:
            locator = page.get_by_text(text, exact=False)
            return locator.count() > 0 and locator.first.is_visible()
        except Exception:
            try:
                return text in page.locator("body").inner_text(timeout=2000)
            except Exception:
                return False

    def _find_first_visible(self, page: Page, factories, *, prefer_last: bool = False) -> Locator | None:
        for factory in factories:
            locator = factory(page)
            try:
                count = locator.count()
            except Exception:
                continue
            indexes = range(count - 1, -1, -1) if prefer_last else range(count)
            for index in indexes:
                candidate = locator.nth(index)
                try:
                    if candidate.is_visible():
                        return candidate
                except Exception:
                    continue
        return None

    def _wait_for_settle(self, page: Page) -> None:
        try:
            page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            page.wait_for_timeout(1000)
