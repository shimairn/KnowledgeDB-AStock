from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json
import mimetypes
import socket
import threading
import webbrowser
from dataclasses import dataclass
from importlib.resources import files
from pathlib import PurePosixPath
from typing import Any, AsyncIterator

import uvicorn
from fastapi import Body, FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse

from ima_bridge.config import Settings
from ima_bridge.output_gc import start_output_gc_thread
from ima_bridge.service import IMAAskService
from ima_bridge.ui_answer_cleaner import clean_answer_html, clean_answer_payload
from ima_bridge.ui_rate_limit import UIRateLimiter
from ima_bridge.worker_pool import WorkerPoolManager, WorkerSlot

RETRY_AFTER_SECONDS = 5
ASSET_CACHE_CONTROL = "public, max-age=3600"
STARTUP_POLL_INTERVAL_MS = 1500
STEADY_POLL_INTERVAL_MS = 15000
UI_ASSET_NAMES = (
    "index.html",
    "app.css",
    "app.js",
    "app-main.js",
)
ASSET_MEDIA_TYPES = {
    ".css": "text/css",
    ".js": "application/javascript",
}


@dataclass(frozen=True, slots=True)
class UIAskRequest:
    question: str
    model: str | None


@dataclass(slots=True)
class UIWorkerLease:
    worker: WorkerSlot
    pool_manager: WorkerPoolManager
    rate_limiter: UIRateLimiter
    client_ip: str
    _released: bool = False

    def release(self, *, response: Any | None = None, exc: Exception | None = None) -> None:
        if self._released:
            return
        if exc is not None:
            self.pool_manager.release(self.worker, exc=exc)
        else:
            self.pool_manager.release(self.worker, response=response)
        self.rate_limiter.release(self.client_ip)
        self._released = True


def _load_asset(name: str) -> str:
    return files("ima_bridge.ui").joinpath(name).read_text(encoding="utf-8")


def _load_ui_assets() -> dict[str, str]:
    return {name: _load_asset(name) for name in UI_ASSET_NAMES}


def _asset_media_type(asset_name: str) -> str | None:
    return ASSET_MEDIA_TYPES.get(PurePosixPath(asset_name).suffix.lower())


def _json_error(error_code: str, error_message: str, status_code: int, **extra: Any) -> JSONResponse:
    payload = {
        "ok": False,
        "error_code": error_code,
        "error_message": error_message,
    }
    payload.update(extra)
    return JSONResponse(status_code=status_code, content=payload)


def _busy_response() -> JSONResponse:
    return _json_error(
        error_code="BUSY",
        error_message="No idle worker available",
        status_code=429,
        retry_after_seconds=RETRY_AFTER_SECONDS,
    )


def _warming_response() -> JSONResponse:
    return _json_error(
        error_code="WARMING_UP",
        error_message="Workers are still initializing",
        status_code=503,
        retry_after_seconds=RETRY_AFTER_SECONDS,
    )


def _rate_limited_response(retry_after_seconds: int) -> JSONResponse:
    return _json_error(
        error_code="RATE_LIMITED",
        error_message="Too many requests from this IP",
        status_code=429,
        retry_after_seconds=retry_after_seconds,
    )


def _extract_payload_text(payload: dict[str, Any] | None, key: str) -> str:
    value = "" if payload is None else payload.get(key, "")
    return str(value).strip()


def _parse_ui_request(payload: dict[str, Any] | None) -> UIAskRequest:
    return UIAskRequest(
        question=_extract_payload_text(payload, "question"),
        model=_extract_payload_text(payload, "model") or None,
    )


def _kb_label(settings: Settings) -> str:
    return settings.kb_label.strip() or "财经知识库"


def _resolve_client_ip(request: Request, settings: Settings) -> str:
    if settings.ui_trust_proxy:
        forwarded_for = request.headers.get("x-forwarded-for", "").strip()
        if forwarded_for:
            return forwarded_for.split(",", 1)[0].strip()

    client = request.client.host if request.client is not None else "unknown"
    return client or "unknown"


def _normalize_stream_update(*args: Any, **kwargs: Any) -> dict[str, str]:
    payload: dict[str, Any]
    if kwargs:
        payload = dict(kwargs)
    elif len(args) == 1 and isinstance(args[0], dict):
        payload = dict(args[0])
    elif len(args) >= 4:
        payload = {
            "phase": args[0],
            "delta": args[1],
            "text": args[2],
            "html": args[3],
        }
    elif len(args) >= 3:
        payload = {
            "phase": args[0],
            "delta": args[1],
            "text": args[2],
        }
    elif len(args) >= 2:
        payload = {
            "phase": "answer",
            "delta": args[0],
            "text": args[1],
        }
    else:
        raise ValueError("Unsupported stream update payload")

    html_value = str(payload.get("html") or payload.get("answer_html") or "")
    phase = str(payload.get("phase") or ("answer_html" if html_value else "answer"))
    return {
        "phase": phase,
        "delta": str(payload.get("delta") or ""),
        "text": str(payload.get("text") or ""),
        "html": html_value,
    }


def _ui_response_payload(response: Any) -> dict[str, Any]:
    return clean_answer_payload(response.model_dump())


def _acquire_ui_worker(
    request: Request,
    payload: dict[str, Any] | None,
    *,
    settings: Settings,
    pool: WorkerPoolManager,
    limiter: UIRateLimiter,
) -> tuple[UIAskRequest | None, UIWorkerLease | None, JSONResponse | None]:
    request_data = _parse_ui_request(payload)
    if not request_data.question:
        return None, None, _json_error("ASK_TIMEOUT", "question is required", status_code=400)

    client_ip = _resolve_client_ip(request, settings)
    decision = limiter.try_acquire(client_ip)
    if not decision.allowed:
        return None, None, _rate_limited_response(decision.retry_after_seconds or 1)

    worker = pool.try_acquire()
    if worker is None:
        limiter.release(client_ip)
        pool_health = pool.health_payload()
        if pool_health.get("status") == "warming" or pool_health.get("error_code") == "WARMING_UP":
            return None, None, _warming_response()
        return None, None, _busy_response()

    return (
        request_data,
        UIWorkerLease(worker=worker, pool_manager=pool, rate_limiter=limiter, client_ip=client_ip),
        None,
    )


async def _build_stream(request: Request, request_data: UIAskRequest, lease: UIWorkerLease) -> AsyncIterator[str]:
    """Stream NDJSON events with a single background thread.

    FastAPI/Starlette will consume async iterables in the event loop directly,
    which avoids the extra "iterate sync generator in threadpool" worker thread.
    """

    loop = asyncio.get_running_loop()
    events: asyncio.Queue[dict[str, Any] | object] = asyncio.Queue()
    done_marker = object()

    def put(item: dict[str, Any] | object) -> None:
        loop.call_soon_threadsafe(events.put_nowait, item)

    yield json.dumps({"type": "start", "question": request_data.question}, ensure_ascii=False) + "\n"

    def on_update(*args: Any, **kwargs: Any) -> None:
        update = _normalize_stream_update(*args, **kwargs)
        phase = update["phase"]
        if phase == "thinking":
            if not update["delta"]:
                return
            put({"type": "thinking_delta", "delta": update["delta"], "text": update["text"]})
            return
        if phase != "answer_html":
            return
        html_snapshot = clean_answer_html(update["html"])
        if not html_snapshot:
            return
        put({"type": "answer_html", "html": html_snapshot})

    ask_future = getattr(lease.worker.service, "ask_with_updates_future", None)
    if callable(ask_future):
        future = ask_future(
            question=request_data.question,
            model=request_data.model,
            on_update=on_update,
        )

        def on_done(done) -> None:
            try:
                response = done.result()
                lease.release(response=response)
                put({"type": "done", "response": _ui_response_payload(response)})
            except Exception as exc:
                lease.release(exc=exc)
                put({"type": "error", "error_code": "CAPTURE_FAILED", "error_message": str(exc)})
            finally:
                put(done_marker)

        future.add_done_callback(on_done)
    else:
        def runner() -> None:
            try:
                response = lease.worker.service.ask_with_updates(
                    question=request_data.question,
                    model=request_data.model,
                    on_update=on_update,
                )
                lease.release(response=response)
                put({"type": "done", "response": _ui_response_payload(response)})
            except Exception as exc:
                lease.release(exc=exc)
                put({"type": "error", "error_code": "CAPTURE_FAILED", "error_message": str(exc)})
            finally:
                put(done_marker)

        threading.Thread(target=runner, daemon=True).start()

    while True:
        item = await events.get()
        if item is done_marker:
            break
        yield json.dumps(item, ensure_ascii=False) + "\n"
        if await request.is_disconnected():
            break


def create_chat_ui_app(
    service: IMAAskService,
    pool_manager: WorkerPoolManager | None = None,
    rate_limiter: UIRateLimiter | None = None,
) -> FastAPI:
    settings = service.settings
    assets = _load_ui_assets()
    pool = pool_manager or WorkerPoolManager(
        template_settings=settings,
        worker_count=settings.ui_worker_count,
    )
    limiter = rate_limiter or UIRateLimiter(
        per_minute=settings.ui_rate_limit_per_minute,
        max_concurrent_per_ip=settings.ui_max_concurrent_per_ip,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        gc_stop = None
        gc_thread = None
        if getattr(settings, "output_gc_enabled", False):
            exclude_dirs = []
            if not getattr(settings, "output_gc_include_profiles", False):
                # Avoid deleting active browser profiles by default. Windows file locks are common here.
                exclude_dirs.extend(
                    [
                        settings.web_profile_dir.parent,
                        settings.managed_profile_dir.parent,
                    ]
                )

            retention_seconds = float(getattr(settings, "output_gc_retention_hours", 24.0)) * 3600.0
            gc_stop, gc_thread = start_output_gc_thread(
                root_dir=settings.artifacts_dir,
                interval_seconds=float(getattr(settings, "output_gc_interval_seconds", 1800.0)),
                retention_seconds=retention_seconds,
                exclude_dirs=exclude_dirs,
            )

        refresh = getattr(pool, "refresh_in_background", None)
        if callable(refresh):
            refresh()
        try:
            yield
        finally:
            if gc_stop is not None:
                gc_stop.set()
            if gc_thread is not None:
                gc_thread.join(timeout=2.0)
            close_pool = getattr(pool, "close", None)
            if callable(close_pool):
                close_pool()

    app = FastAPI(lifespan=lifespan)
    app.state.settings = settings
    app.state.service = service
    app.state.pool_manager = pool
    app.state.rate_limiter = limiter

    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        return HTMLResponse(assets["index.html"], headers={"Cache-Control": "no-store"})

    @app.get("/assets/{asset_name:path}")
    def asset(asset_name: str) -> Response:
        normalized_name = PurePosixPath(asset_name).as_posix().lstrip("/")
        content = assets.get(normalized_name)
        media_type = _asset_media_type(normalized_name)
        if content is None or media_type is None:
            return Response(status_code=404)
        return Response(content=content, media_type=media_type, headers={"Cache-Control": ASSET_CACHE_CONTROL})

    @app.get("/api/ui-config")
    def api_ui_config() -> JSONResponse:
        summary = pool.summarize()
        model_catalog = pool.get_model_catalog()
        health = pool.health_payload()
        return JSONResponse(
            {
                "ok": True,
                "kb_label": _kb_label(settings),
                "auth_required": False,
                "driver_mode": settings.driver_mode,
                "workers_total": summary.workers_total,
                "health": health,
                "startup_poll_interval_ms": STARTUP_POLL_INTERVAL_MS,
                "steady_poll_interval_ms": STEADY_POLL_INTERVAL_MS,
                **model_catalog.model_dump(),
            }
        )

    @app.get("/api/health.ok")
    def api_health_ok() -> JSONResponse:
        payload = pool.health_payload()
        return JSONResponse({"ok": bool(payload.get("ok"))})

    @app.get("/api/health")
    def api_health() -> JSONResponse:
        return JSONResponse(pool.health_payload())

    @app.get("/api/media/{instance}/{media_name:path}")
    def api_media(instance: str, media_name: str) -> Response:
        base_dir = (settings.artifacts_dir / "ui-media").resolve()
        candidate = (base_dir / instance / media_name).resolve()
        try:
            candidate.relative_to(base_dir)
        except ValueError:
            return Response(status_code=404)
        if not candidate.exists() or not candidate.is_file():
            return Response(status_code=404)
        media_type, _ = mimetypes.guess_type(str(candidate))
        return FileResponse(
            path=str(candidate),
            media_type=media_type or "application/octet-stream",
            headers={"Cache-Control": "no-store"},
        )

    @app.post("/api/ask")
    def api_ask(request: Request, payload: dict[str, Any] | None = Body(default=None)) -> JSONResponse:
        request_data, lease, error_response = _acquire_ui_worker(
            request,
            payload,
            settings=settings,
            pool=pool,
            limiter=limiter,
        )
        if error_response is not None:
            return error_response

        try:
            response = lease.worker.service.ask(question=request_data.question, model=request_data.model)
            lease.release(response=response)
            return JSONResponse(_ui_response_payload(response))
        except Exception as exc:
            lease.release(exc=exc)
            return _json_error("CAPTURE_FAILED", str(exc), status_code=500)

    @app.post("/api/ask-stream")
    async def api_ask_stream(request: Request, payload: dict[str, Any] | None = Body(default=None)) -> Response:
        request_data, lease, error_response = _acquire_ui_worker(
            request,
            payload,
            settings=settings,
            pool=pool,
            limiter=limiter,
        )
        if error_response is not None:
            return error_response

        return StreamingResponse(
            _build_stream(request=request, request_data=request_data, lease=lease),
            media_type="application/x-ndjson",
            headers={"Cache-Control": "no-store"},
        )

    return app


def run_chat_ui(
    service: IMAAskService,
    host: str,
    port: int,
    open_browser: bool,
    workers: int | None = None,
) -> int:
    if service.settings.driver_mode != "web":
        print("ui concurrent service only supports --driver web")
        return 2

    # Fail fast before starting background worker warmup threads.
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError:
        infos = [(socket.AF_INET, socket.SOCK_STREAM, 0, "", (host, port))]

    port_in_use = True
    for family, socktype, proto, _canon, sockaddr in infos:
        try:
            sock = socket.socket(family, socktype, proto)
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            except OSError:
                pass
            sock.bind(sockaddr)
        except OSError:
            continue
        else:
            port_in_use = False
            sock.close()
            break

    if port_in_use:
        print(f"ui failed: port already in use: {host}:{port}")
        return 2

    pool_manager = WorkerPoolManager(
        template_settings=service.settings,
        worker_count=workers if workers is not None else service.settings.ui_worker_count,
    )
    pool_manager.seed_profiles_from(service.settings)
    app = create_chat_ui_app(service=service, pool_manager=pool_manager)

    browser_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    url = f"http://{browser_host}:{port}/"
    print(f"ui running: {url}")
    if open_browser:
        webbrowser.open(url)

    try:
        uvicorn.run(app, host=host, port=port, log_level="warning")
    finally:
        # If uvicorn fails to start (e.g. bind error), the app lifespan won't run,
        # so ensure worker resources are still cleaned up.
        close_pool = getattr(pool_manager, "close", None)
        if callable(close_pool):
            close_pool()
    return 0
