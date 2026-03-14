from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
import re
import threading
import time
from typing import Callable

from playwright.sync_api import BrowserContext, Error as PlaywrightError, Page, Playwright, sync_playwright

from ima_bridge._web.session import WebSession
from ima_bridge.config import Settings
from ima_bridge.driver_protocol import (
    AskDriver,
    DriverAskResult,
    DriverHealthStatus,
    DriverLoginStatus,
    DriverModelCatalog,
)
from ima_bridge.errors import AskCancelledError, CaptureFailedError
from ima_bridge.service import IMAAskService
from ima_bridge.ui_media import (
    download_images_to_local,
    extract_img_srcs,
    inject_placeholder_img_sources,
    rewrite_img_sources,
)
from ima_bridge.web_driver import WebAskDriver
from ima_bridge.utils import get_logger, timestamp_slug

logger = get_logger("ima_bridge.web_worker_service")
_VECTOR_PLACEHOLDER_RE = re.compile(r"data-ima-bridge-media=(?:\"|')(vector-\d+)(?:\"|')", re.IGNORECASE)


def _is_local_ui_src(src: str) -> bool:
    value = str(src or "").strip()
    return value.startswith("/api/") or value.startswith("/assets/")


def _snapshot_vector_media(
    *,
    web_driver: WebAskDriver,
    page: Page,
    output_dir,
    instance: str,
    placeholders: list[str],
    max_vectors: int,
    stamp: str,
    existing: dict[str, str] | None = None,
) -> dict[str, str]:
    """Best-effort snapshot for svg/canvas charts that were replaced with <img data-ima-bridge-media="vector-N">."""

    existing = dict(existing or {})
    placeholder_urls: dict[str, str] = {}
    if not placeholders or max_vectors <= 0:
        return placeholder_urls

    try:
        target = web_driver.answer_extractor.find_latest_ai_nodes(page)
    except Exception:
        target = None
    if target is None:
        return placeholder_urls

    _container, bubble = target
    root = bubble.locator("div[class*='_markdown_']").first
    try:
        if root.count() == 0:
            root = bubble
    except Exception:
        root = bubble

    media = root.locator("svg,canvas")
    try:
        media_count = media.count()
    except Exception:
        media_count = 0
    if media_count <= 0:
        return placeholder_urls

    try:
        output_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        return placeholder_urls

    limit = min(media_count, len(placeholders), max_vectors)
    for i in range(limit):
        placeholder_id = placeholders[i]
        if placeholder_id in existing:
            continue
        filename = f"{placeholder_id}-{stamp}-{i}.png"
        path = output_dir / filename
        try:
            media.nth(i).screenshot(path=str(path))
        except Exception:
            continue
        existing_url = f"/api/media/{instance}/{filename}"
        existing[placeholder_id] = existing_url
        placeholder_urls[placeholder_id] = existing_url
    return placeholder_urls


class StreamAnswerHtmlLocalizer:
    def __init__(
        self,
        *,
        settings: Settings,
        web_driver: WebAskDriver,
        page: Page,
        context: BrowserContext,
        output_dir,
        url_prefix: str,
        max_images: int,
        interval_ms: int,
        src_cache: dict[str, str],
        placeholder_cache: dict[str, str],
    ) -> None:
        self.settings = settings
        self.web_driver = web_driver
        self.page = page
        self.context = context
        self.output_dir = output_dir
        self.url_prefix = str(url_prefix or "")
        self.max_images = max(0, int(max_images))
        self.interval_seconds = max(0.0, float(interval_ms) / 1000.0)
        self.src_cache = src_cache
        self.placeholder_cache = placeholder_cache
        self._last_heavy_at = 0.0
        self._stamp = timestamp_slug()

    def _needs_heavy_work(self, html: str) -> bool:
        if self.max_images > 0:
            for src in extract_img_srcs(html):
                if not _is_local_ui_src(src):
                    return True
        placeholders = _VECTOR_PLACEHOLDER_RE.findall(html or "")
        return any(pid not in self.placeholder_cache for pid in placeholders)

    def _localize_impl(
        self,
        html: str,
        *,
        max_images: int,
        max_bytes: int,
        max_total_bytes: int,
        max_data_uri_chars: int,
        max_vectors: int,
    ) -> str:
        localized_html = rewrite_img_sources(html, self.src_cache, placeholder_map=self.placeholder_cache)
        localized, items = download_images_to_local(
            page=self.page,
            context=self.context,
            answer_html=localized_html,
            output_dir=self.output_dir,
            url_prefix=self.url_prefix,
            max_images=max_images,
            max_bytes=max_bytes,
            max_total_bytes=max_total_bytes,
            max_data_uri_chars=max_data_uri_chars,
        )
        for media in items:
            local_url = f"{self.url_prefix.rstrip('/')}/{media.local_relpath}"
            self.src_cache[media.original_src] = local_url
        localized_html = localized

        placeholders = _VECTOR_PLACEHOLDER_RE.findall(localized_html)
        if placeholders and max_vectors > 0:
            created = _snapshot_vector_media(
                web_driver=self.web_driver,
                page=self.page,
                output_dir=self.output_dir,
                instance=self.settings.instance,
                placeholders=placeholders,
                max_vectors=max_vectors,
                stamp=self._stamp,
                existing=self.placeholder_cache,
            )
            if created:
                self.placeholder_cache.update(created)
                localized_html = inject_placeholder_img_sources(localized_html, created)
        return localized_html

    def localize_stream(self, html: str) -> str:
        source = str(html or "").strip()
        if not source:
            return ""
        # Cheap path: apply cached rewrites immediately for each snapshot.
        rewritten = rewrite_img_sources(source, self.src_cache, placeholder_map=self.placeholder_cache)

        if self.interval_seconds <= 0:
            return self._localize_impl(
                rewritten,
                max_images=self.max_images,
                max_bytes=8 * 1024 * 1024,
                max_total_bytes=10 * 1024 * 1024,
                max_data_uri_chars=1 * 1024 * 1024,
                max_vectors=max(0, int(getattr(self.settings, "web_vector_snapshot_max", 6))),
            )

        now = time.monotonic()
        if now - float(self._last_heavy_at or 0.0) < self.interval_seconds:
            return rewritten
        if not self._needs_heavy_work(rewritten):
            return rewritten

        self._last_heavy_at = now
        return self._localize_impl(
            rewritten,
            max_images=self.max_images,
            max_bytes=8 * 1024 * 1024,
            max_total_bytes=10 * 1024 * 1024,
            max_data_uri_chars=1 * 1024 * 1024,
            max_vectors=max(0, int(getattr(self.settings, "web_vector_snapshot_max", 6))),
        )

    def localize_final(self, html: str) -> str:
        source = str(html or "").strip()
        if not source:
            return ""
        return self._localize_impl(
            source,
            max_images=16,
            max_bytes=25 * 1024 * 1024,
            max_total_bytes=25 * 1024 * 1024,
            max_data_uri_chars=4 * 1024 * 1024,
            max_vectors=max(0, int(getattr(self.settings, "web_vector_snapshot_max", 6))),
        )


class PersistentWebAskDriver(AskDriver):
    """Thread-bound AskDriver that keeps a persistent BrowserContext alive.

    This must only be used from a single thread. Use WebWorkerService to ensure
    thread affinity.
    """

    source_driver = "web"

    def __init__(self, settings: Settings, web_driver: WebAskDriver | None = None) -> None:
        self.settings = settings
        self.web_driver = web_driver or WebAskDriver(settings)
        self._playwright: Playwright | None = None
        self._context: BrowserContext | None = None
        self._context_headless: bool | None = None
        self._request_count = 0
        self._last_context_at = 0.0
        self._ui_conversation_id: str | None = None

    def close(self) -> None:
        self._close_context()
        if self._playwright is not None:
            try:
                self._playwright.stop()
            except Exception:
                pass
        self._playwright = None

    def health(self) -> DriverHealthStatus:
        try:
            ok, error_code, error_message = self._health_impl(headless=self.settings.web_headless)
            return DriverHealthStatus(
                ok=ok,
                source_driver="web",
                base_url=self.settings.web_base_url,
                profile_dir=str(self.settings.web_profile_dir.resolve()),
                headless=self.settings.web_headless,
                managed_profile_dir=str(self.settings.managed_profile_dir.resolve()),
                error_code=error_code,
                error_message=error_message,
            )
        except Exception as exc:
            # Reset the context on unexpected failures so the next call can recover.
            self._close_context()
            return DriverHealthStatus(
                ok=False,
                source_driver="web",
                base_url=self.settings.web_base_url,
                profile_dir=str(self.settings.web_profile_dir.resolve()),
                headless=self.settings.web_headless,
                managed_profile_dir=str(self.settings.managed_profile_dir.resolve()),
                error_code="CAPTURE_FAILED",
                error_message=str(exc),
            )

    def login(self, timeout_seconds: float | None = None) -> DriverLoginStatus:
        timeout = timeout_seconds if timeout_seconds is not None else self.settings.login_timeout_seconds
        try:
            ok, error_code, error_message = self._login_impl(timeout_seconds=timeout)
            return DriverLoginStatus(
                ok=ok,
                source_driver="web",
                base_url=self.settings.web_base_url,
                profile_dir=str(self.settings.web_profile_dir.resolve()),
                timeout_seconds=timeout,
                error_code=error_code,
                error_message=error_message,
            )
        except Exception as exc:
            self._close_context()
            return DriverLoginStatus(
                ok=False,
                source_driver="web",
                base_url=self.settings.web_base_url,
                profile_dir=str(self.settings.web_profile_dir.resolve()),
                timeout_seconds=timeout,
                error_code="CAPTURE_FAILED",
                error_message=str(exc),
            )

    def get_model_catalog(self) -> DriverModelCatalog:
        self._ensure_context(headless=self.settings.web_headless)
        page = self._safe_prepare_chat_page()
        return self.web_driver.conversation.discover_model_catalog(
            page,
            preferred_model=self.settings.model_prefix,
            strict=False,
        )

    def ask(
        self,
        question: str,
        model: str | None = None,
        on_update: Callable[..., None] | None = None,
        cancel_event: threading.Event | None = None,
        conversation_id: str | None = None,
        reset_conversation: bool = False,
    ) -> DriverAskResult:
        self._ensure_context(headless=self.settings.web_headless)
        return self._ask_in_context(
            question=question,
            model=model,
            on_update=on_update,
            cancel_event=cancel_event,
            conversation_id=conversation_id,
            reset_conversation=reset_conversation,
        )

    def _ensure_playwright(self) -> Playwright:
        if self._playwright is not None:
            return self._playwright
        self._playwright = sync_playwright().start()
        return self._playwright

    def _ensure_context(self, *, headless: bool) -> BrowserContext:
        context = self._context
        if context is not None and self._context_headless == headless:
            try:
                pages = list(context.pages)
            except Exception:
                self._close_context()
            else:
                now = time.monotonic()
                should_recycle = False
                reason = ""

                if self._request_count >= max(1, int(getattr(self.settings, "web_context_max_requests", 60))):
                    should_recycle = True
                    reason = "max_requests"
                elif now - float(self._last_context_at or 0.0) >= max(
                    1.0, float(getattr(self.settings, "web_context_max_age_seconds", 3600.0))
                ):
                    should_recycle = True
                    reason = "max_age"
                else:
                    max_pages = max(1, int(getattr(self.settings, "web_context_max_pages", 2)))
                    if len(pages) > max_pages:
                        should_recycle = True
                        reason = "max_pages"

                if not should_recycle:
                    return context

                logger.info(
                    "recycling web context: reason=%s instance=%s requests=%s pages=%s",
                    reason,
                    self.settings.instance,
                    self._request_count,
                    len(pages),
                )
                self._close_context()

        self._close_context()

        playwright = self._ensure_playwright()
        context = self.web_driver.session.launch_context(playwright, headless=headless)
        self._context = context
        self._context_headless = headless
        self._last_context_at = time.monotonic()
        self._request_count = 0
        return context

    def _close_context(self) -> None:
        if self._context is not None:
            try:
                self._context.close()
            except Exception:
                pass
        self._context = None
        self._context_headless = None
        self._ui_conversation_id = None

    def _safe_prepare_chat_page(self) -> Page:
        if self._context is None:
            raise CaptureFailedError("web context not initialized")
        try:
            return self.web_driver._prepare_chat_page(self._context)
        except PlaywrightError:
            # If the page/context crashed, rebuild once.
            self._close_context()
            self._ensure_context(headless=self.settings.web_headless)
            if self._context is None:
                raise
            return self.web_driver._prepare_chat_page(self._context)

    def _health_impl(self, *, headless: bool) -> tuple[bool, str | None, str | None]:
        context = self._ensure_context(headless=headless)
        session: WebSession = self.web_driver.session
        page = session.acquire_page(context)

        if self.web_driver.kb_navigator.try_open_remembered_target(page):
            return True, None, None

        session.open_home(page)
        text = session.body_text(page)
        if self.web_driver.kb_navigator.is_login_required(text):
            return False, "LOGIN_REQUIRED", "Web profile requires login. Run `python -m ima_bridge login` once."
        if self.web_driver.kb_navigator.confirm_target_context(page):
            return True, None, None

        self.web_driver.kb_navigator.open_kb_hub(page)
        text = session.body_text(page)
        if self.web_driver.kb_navigator.is_login_required(text):
            return False, "LOGIN_REQUIRED", "Web profile requires login. Run `python -m ima_bridge login` once."
        if self.web_driver.kb_navigator.confirm_target_context(page) or self.web_driver.kb_navigator.probe_target_entries(page):
            return True, None, None
        return (
            False,
            "KB_NOT_FOUND",
            f"Target knowledge base not confirmed: name={self.settings.kb_name}, owner={self.settings.kb_owner}, title={self.settings.kb_title}",
        )

    def _login_impl(self, *, timeout_seconds: float) -> tuple[bool, str | None, str | None]:
        # QR login must be headed; close any headless context first.
        self._close_context()
        context = self._ensure_context(headless=False)
        session: WebSession = self.web_driver.session
        page = session.acquire_page(context)

        session.open_home(page)
        if self.web_driver.kb_navigator.try_open_remembered_target(page):
            self._close_context()
            return True, None, None

        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            target_page = self.web_driver.kb_navigator.find_target_page(session.active_pages(context))
            if target_page is not None:
                self.web_driver.kb_navigator.remember_target_url(target_page)
                self._close_context()
                return True, None, None
            session.wait_for_page_activity(context, 1000)

        self._close_context()
        return False, "LOGIN_REQUIRED", "Login timeout. Scan QR and open target knowledge base, then retry."

    def _ask_in_context(
        self,
        *,
        question: str,
        model: str | None,
        on_update: Callable[..., None] | None,
        cancel_event: threading.Event | None,
        conversation_id: str | None,
        reset_conversation: bool,
    ) -> DriverAskResult:
        page = self._safe_prepare_chat_page()
        context = page.context
        normalized_conversation_id = str(conversation_id or "").strip() or None
        should_reset = bool(reset_conversation)
        if normalized_conversation_id is None:
            # Backwards-compat: without an explicit conversation id, keep the old "single-turn" behavior.
            should_reset = True
        elif self._ui_conversation_id is None or self._ui_conversation_id != normalized_conversation_id:
            should_reset = True

        if should_reset:
            self.web_driver.conversation.start_new_conversation(page)
            self._ui_conversation_id = normalized_conversation_id
        selected_model = self.web_driver.conversation.ensure_selected_model(page, requested_model=model)

        before_text = self.web_driver.session.body_text(page)
        before_html = self.web_driver.session.body_html(page)
        self.web_driver.conversation.submit_question(page, question)

        output_dir = self.settings.artifacts_dir / "ui-media" / self.settings.instance
        url_prefix = f"/api/media/{self.settings.instance}"
        src_cache: dict[str, str] = {}
        placeholder_cache: dict[str, str] = {}

        stream_localizer: StreamAnswerHtmlLocalizer | None = None
        wrapped_on_update = on_update
        if callable(on_update) and bool(getattr(self.settings, "ui_stream_localize_media", True)):
            stream_localizer = StreamAnswerHtmlLocalizer(
                settings=self.settings,
                web_driver=self.web_driver,
                page=page,
                context=context,
                output_dir=output_dir,
                url_prefix=url_prefix,
                max_images=int(getattr(self.settings, "ui_stream_localize_max_images", 4)),
                interval_ms=int(getattr(self.settings, "ui_stream_localize_interval_ms", 800)),
                src_cache=src_cache,
                placeholder_cache=placeholder_cache,
            )

            def _on_update_wrapped(*args, **kwargs):  # type: ignore[no-redef]
                if cancel_event is not None and cancel_event.is_set():
                    return
                if not callable(on_update):
                    return

                payload = None
                if kwargs:
                    payload = dict(kwargs)
                elif len(args) == 1 and isinstance(args[0], dict):
                    payload = dict(args[0])

                if payload is None:
                    on_update(*args, **kwargs)
                    return

                phase = str(payload.get("phase") or ("answer_html" if payload.get("html") else ""))
                if phase != "answer_html":
                    on_update(payload)
                    return

                html_value = str(payload.get("html") or payload.get("answer_html") or "")
                if not html_value.strip():
                    on_update(payload)
                    return

                try:
                    localized_html = stream_localizer.localize_stream(html_value) if stream_localizer else html_value
                except Exception:
                    localized_html = html_value

                if localized_html != html_value:
                    payload["html"] = localized_html
                on_update(payload)

            wrapped_on_update = _on_update_wrapped

        after_text, after_html = self.web_driver.conversation.wait_answer(
            page,
            before_text,
            question=question,
            on_update=wrapped_on_update,
            cancel_event=cancel_event,
        )

        latest_block = self.web_driver.answer_extractor.extract_latest_ai_block(page)
        if latest_block is not None:
            answer_text, answer_html, thinking_text = latest_block
        else:
            answer_text = self.web_driver.answer_extractor.extract_answer_text(before_text, after_text, question)
            if not answer_text:
                raise CaptureFailedError("Answer text not detected after completion")
            answer_html = after_html if after_html != before_html else ""
            thinking_text = self.web_driver.answer_extractor.extract_latest_thinking_text(page)

        if cancel_event is not None and cancel_event.is_set():
            raise AskCancelledError("Client disconnected")

        references = self.web_driver.answer_extractor.extract_references(answer_text)
        screenshot = self.web_driver.answer_extractor.capture(page) if self.settings.capture_screenshot else None
        self._request_count += 1

        localized_html = answer_html
        if localized_html:
            try:
                final_localizer = stream_localizer or StreamAnswerHtmlLocalizer(
                    settings=self.settings,
                    web_driver=self.web_driver,
                    page=page,
                    context=context,
                    output_dir=output_dir,
                    url_prefix=url_prefix,
                    max_images=0,
                    interval_ms=0,
                    src_cache=src_cache,
                    placeholder_cache=placeholder_cache,
                )
                localized_html = final_localizer.localize_final(localized_html)
            except Exception:
                localized_html = answer_html
        return DriverAskResult(
            source_driver="web",
            model=selected_model,
            thinking_text=thinking_text,
            answer_text=answer_text,
            answer_html=localized_html,
            references=references,
            screenshot_path=screenshot,
        )


class WebWorkerService:
    """Expose IMAAskService methods, but execute everything in a dedicated thread."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._driver = PersistentWebAskDriver(settings=settings)
        self._service = IMAAskService(settings=settings, driver=self._driver)
        self._executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix=f"ima-web-{settings.instance}",
        )
        self._closed = False
        self._close_lock = threading.Lock()

    def close(self) -> None:
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
        try:
            future = self._executor.submit(self._driver.close)
            future.result(timeout=10)
        except Exception:
            pass
        self._executor.shutdown(wait=False, cancel_futures=False)

    def _submit(self, fn, *args, **kwargs) -> Future:
        if self._closed:
            raise RuntimeError("worker service is closed")
        return self._executor.submit(fn, *args, **kwargs)

    def health(self):
        return self._submit(self._service.health).result()

    def login(self, timeout_seconds: float | None = None):
        return self._submit(self._service.login, timeout_seconds).result()

    def get_model_catalog(self) -> DriverModelCatalog:
        return self._submit(self._service.get_model_catalog).result()

    def ask(
        self,
        question: str,
        model: str | None = None,
        conversation_id: str | None = None,
        reset_conversation: bool = False,
    ):
        return self._submit(
            self._service.ask_with_updates,
            question,
            model,
            None,
            None,
            conversation_id,
            reset_conversation,
        ).result()

    def ask_with_updates(
        self,
        question: str,
        model: str | None = None,
        on_update: Callable[..., None] | None = None,
        cancel_event: threading.Event | None = None,
        conversation_id: str | None = None,
        reset_conversation: bool = False,
    ):
        return self._submit(
            self._service.ask_with_updates,
            question,
            model,
            on_update,
            cancel_event,
            conversation_id,
            reset_conversation,
        ).result()

    def ask_with_updates_future(
        self,
        question: str,
        model: str | None = None,
        on_update: Callable[..., None] | None = None,
        cancel_event: threading.Event | None = None,
        conversation_id: str | None = None,
        reset_conversation: bool = False,
    ) -> Future:
        return self._submit(
            self._service.ask_with_updates,
            question,
            model,
            on_update,
            cancel_event,
            conversation_id,
            reset_conversation,
        )
