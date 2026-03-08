from __future__ import annotations

import re

from playwright.sync_api import Locator, Page

from ima_bridge.config import Settings
from ima_bridge.errors import KBNotFoundError, LoginRequiredError
from ima_bridge.probes import CONTENT_PREFIX, INPUT_HINT, KB_NAV_TEXTS, LOGIN_HINTS, MIN_TARGET_SCORE
from ima_bridge.target_state import TargetStateStore

from .session import WebSession

_CANONICAL_TEXT_RE = re.compile(r"[^0-9a-zA-Z\u4e00-\u9fff]+")


class WebKnowledgeBaseNavigator:
    def __init__(self, settings: Settings, session: WebSession, store: TargetStateStore) -> None:
        self.settings = settings
        self.session = session
        self.store = store

    def ensure_login(self, page: Page) -> None:
        text = self.session.body_text(page)
        if self.is_login_required(text):
            raise LoginRequiredError("Web profile requires login. Run `python -m ima_bridge login` once.")

    def is_login_required(self, body_text: str) -> bool:
        return any(hint in body_text for hint in LOGIN_HINTS)

    def ensure_target_kb(self, page: Page) -> None:
        if self.confirm_target_context(page):
            return

        self.open_kb_hub(page)
        self.ensure_login(page)
        if self.confirm_target_context(page):
            return
        if self.probe_target_entries(page):
            return

        for nav in KB_NAV_TEXTS:
            nav_locator = page.get_by_text(nav, exact=False)
            if self.click_locator_candidates(page, nav_locator):
                page.wait_for_timeout(700)
                self.ensure_login(page)
                if self.confirm_target_context(page):
                    return
                if self.probe_target_entries(page):
                    return

        raise KBNotFoundError(
            f"Target knowledge base not confirmed: name={self.settings.kb_name}, owner={self.settings.kb_owner}, title={self.settings.kb_title}"
        )

    def open_kb_hub(self, page: Page) -> None:
        hub_url = self.settings.web_base_url.rstrip("/") + "/wikis"
        try:
            page.goto(hub_url, wait_until="domcontentloaded")
            page.wait_for_timeout(900)
        except Exception:
            return

    def probe_target_entries(self, page: Page) -> bool:
        for probe in self._probe_texts():
            locator = page.get_by_text(probe, exact=False)
            if not self.click_locator_candidates(page, locator):
                continue
            page.wait_for_timeout(900)
            if self.confirm_target_context(page):
                return True
        return False

    def has_target_signals(self, body_text: str) -> bool:
        if self.identity_score(body_text) <= 0:
            return False
        return self.target_score(body_text) >= MIN_TARGET_SCORE

    def target_score(self, body_text: str) -> int:
        score = self.identity_score(body_text)
        if CONTENT_PREFIX in body_text:
            score += 2
        if INPUT_HINT in body_text:
            score += 1
        return score

    def identity_score(self, body_text: str) -> int:
        score = 0
        if self._contains(body_text, self.settings.kb_title):
            score += 3
        if self._contains(body_text, self.settings.kb_name):
            score += 2
        if self._contains(body_text, self.settings.kb_owner):
            score += 1
        return score

    def find_target_page(self, pages: list[Page]) -> Page | None:
        best_page: Page | None = None
        best_score = -1
        for candidate in pages:
            text = self.session.body_text(candidate)
            score = self.target_score(text)
            if score > best_score:
                best_score = score
                best_page = candidate
        if best_page is None:
            return None
        return best_page if best_score >= MIN_TARGET_SCORE else None

    def confirm_target_context(self, page: Page) -> bool:
        body_text = self.session.body_text(page)
        if self.has_target_signals(body_text):
            self.remember_target_url(page, body_text)
            return True

        target_page = self.find_target_page(page.context.pages)
        if target_page is None:
            return False

        target_text = self.session.body_text(target_page)
        if not self.has_target_signals(target_text):
            return False

        self.remember_target_url(target_page, target_text)
        return True

    def click_locator_candidates(self, page: Page, locator: Locator, max_candidates: int = 8) -> bool:
        try:
            count = locator.count()
        except Exception:
            return False

        for index in range(min(count, max_candidates)):
            candidate = locator.nth(index)
            if self.click_with_fallback(page, candidate):
                return True
        return False

    def click_with_fallback(self, page: Page, locator: Locator) -> bool:
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

    def try_open_remembered_target(self, page: Page) -> bool:
        remembered = self.store.load()
        if not remembered:
            return False
        try:
            page.goto(remembered, wait_until="domcontentloaded")
            page.wait_for_timeout(800)
        except Exception:
            return False

        if self.confirm_target_context(page):
            return True
        self.store.clear()
        return False

    def remember_target_url(self, page: Page, body_text: str | None = None) -> None:
        url = (page.url or "").strip()
        text = body_text if body_text is not None else self.session.body_text(page)
        self.store.remember(url, text, self.has_target_signals)

    def can_persist_target_url(self, url: str, body_text: str) -> bool:
        return self.store.can_persist(url, body_text, self.has_target_signals)

    def _probe_texts(self) -> list[str]:
        probes = [self.settings.kb_title, self.settings.kb_name, self.settings.kb_owner]
        seen: set[str] = set()
        ordered: list[str] = []
        for probe in probes:
            value = (probe or "").strip()
            if not value or value in seen:
                continue
            seen.add(value)
            ordered.append(value)
        return ordered

    def _contains(self, body_text: str, target: str) -> bool:
        body = self._canonical_text(body_text)
        needle = self._canonical_text(target)
        return bool(body and needle and needle in body)

    def _canonical_text(self, value: str) -> str:
        return _CANONICAL_TEXT_RE.sub("", (value or "").strip()).lower()
