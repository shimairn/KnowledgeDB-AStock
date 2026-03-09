from __future__ import annotations

import json
import queue
import threading
import webbrowser
from importlib.resources import files
from typing import Any, Iterator

import uvicorn
from fastapi import Body, FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse

from ima_bridge.config import Settings
from ima_bridge.service import IMAAskService
from ima_bridge.ui_rate_limit import UIRateLimiter
from ima_bridge.worker_pool import WorkerPoolManager, WorkerSlot

RETRY_AFTER_SECONDS = 5


def _load_asset(name: str) -> str:
    return files("ima_bridge.ui").joinpath(name).read_text(encoding="utf-8")


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


def _rate_limited_response(retry_after_seconds: int) -> JSONResponse:
    return _json_error(
        error_code="RATE_LIMITED",
        error_message="Too many requests from this IP",
        status_code=429,
        retry_after_seconds=retry_after_seconds,
    )


def _extract_question(payload: dict[str, Any] | None) -> str:
    value = "" if payload is None else payload.get("question", "")
    return str(value).strip()


def _extract_model(payload: dict[str, Any] | None) -> str | None:
    value = "" if payload is None else payload.get("model", "")
    normalized = str(value).strip()
    return normalized or None


def _kb_label(settings: Settings) -> str:
    return f"{settings.kb_name} / {settings.kb_owner} / {settings.kb_title}"


def _resolve_client_ip(request: Request, settings: Settings) -> str:
    if settings.ui_trust_proxy:
        forwarded_for = request.headers.get("x-forwarded-for", "").strip()
        if forwarded_for:
            return forwarded_for.split(",", 1)[0].strip()

    client = request.client.host if request.client is not None else "unknown"
    return client or "unknown"


def _normalize_stream_update(*args: Any, **kwargs: Any) -> tuple[str, str, str]:
    if kwargs:
        phase = str(kwargs.get("phase") or "answer")
        delta = str(kwargs.get("delta") or "")
        text = str(kwargs.get("text") or "")
        return phase, delta, text

    if len(args) == 1 and isinstance(args[0], dict):
        payload = args[0]
        return (
            str(payload.get("phase") or "answer"),
            str(payload.get("delta") or ""),
            str(payload.get("text") or ""),
        )

    if len(args) >= 3:
        return str(args[0] or "answer"), str(args[1] or ""), str(args[2] or "")

    if len(args) >= 2:
        return "answer", str(args[0] or ""), str(args[1] or "")

    raise ValueError("Unsupported stream update payload")


def _build_stream(
    worker: WorkerSlot,
    pool_manager: WorkerPoolManager,
    rate_limiter: UIRateLimiter,
    client_ip: str,
    question: str,
    model: str | None,
) -> Iterator[str]:
    events: queue.Queue[dict[str, Any] | object] = queue.Queue()
    done_marker = object()

    def runner() -> None:
        try:
            events.put({"type": "start", "question": question})

            def on_update(*args: Any, **kwargs: Any) -> None:
                phase, delta, text = _normalize_stream_update(*args, **kwargs)
                if not delta:
                    return
                event_type = "thinking_delta" if phase == "thinking" else "delta"
                events.put({"type": event_type, "delta": delta, "text": text})

            response = worker.service.ask_with_updates(question=question, model=model, on_update=on_update)
            pool_manager.release(worker, response=response)
            events.put({"type": "done", "response": response.model_dump()})
        except Exception as exc:
            pool_manager.release(worker, exc=exc)
            events.put(
                {
                    "type": "error",
                    "error_code": "CAPTURE_FAILED",
                    "error_message": str(exc),
                }
            )
        finally:
            rate_limiter.release(client_ip)
            events.put(done_marker)

    threading.Thread(target=runner, daemon=True).start()

    while True:
        item = events.get()
        if item is done_marker:
            break
        yield json.dumps(item, ensure_ascii=False) + "\n"


def create_chat_ui_app(
    service: IMAAskService,
    pool_manager: WorkerPoolManager | None = None,
    rate_limiter: UIRateLimiter | None = None,
) -> FastAPI:
    settings = service.settings
    assets = {
        "index.html": _load_asset("index.html"),
        "app.css": _load_asset("app.css"),
        "app.js": _load_asset("app.js"),
    }
    pool = pool_manager or WorkerPoolManager(
        template_settings=settings,
        worker_count=settings.ui_worker_count,
    )
    limiter = rate_limiter or UIRateLimiter(
        per_minute=settings.ui_rate_limit_per_minute,
        max_concurrent_per_ip=settings.ui_max_concurrent_per_ip,
    )

    app = FastAPI()
    app.state.settings = settings
    app.state.service = service
    app.state.pool_manager = pool
    app.state.rate_limiter = limiter

    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        return HTMLResponse(assets["index.html"], headers={"Cache-Control": "no-store"})

    @app.get("/assets/app.css")
    def asset_css() -> Response:
        return Response(content=assets["app.css"], media_type="text/css")

    @app.get("/assets/app.js")
    def asset_js() -> Response:
        return Response(content=assets["app.js"], media_type="application/javascript")

    @app.get("/api/ui-config")
    def api_ui_config() -> JSONResponse:
        summary = pool.summarize()
        model_catalog = pool.get_model_catalog()
        return JSONResponse(
            {
                "ok": True,
                "kb_label": _kb_label(settings),
                "auth_required": False,
                "driver_mode": settings.driver_mode,
                "workers_total": summary.workers_total,
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

    @app.post("/api/ask")
    def api_ask(request: Request, payload: dict[str, Any] | None = Body(default=None)) -> JSONResponse:
        question = _extract_question(payload)
        model = _extract_model(payload)
        if not question:
            return _json_error("ASK_TIMEOUT", "question is required", status_code=400)

        client_ip = _resolve_client_ip(request, settings)
        decision = limiter.try_acquire(client_ip)
        if not decision.allowed:
            return _rate_limited_response(decision.retry_after_seconds or 1)

        worker = pool.try_acquire()
        if worker is None:
            limiter.release(client_ip)
            return _busy_response()

        try:
            response = worker.service.ask(question=question, model=model)
            pool.release(worker, response=response)
            return JSONResponse(response.model_dump())
        except Exception as exc:
            pool.release(worker, exc=exc)
            return _json_error("CAPTURE_FAILED", str(exc), status_code=500)
        finally:
            limiter.release(client_ip)

    @app.post("/api/ask-stream")
    def api_ask_stream(request: Request, payload: dict[str, Any] | None = Body(default=None)) -> Response:
        question = _extract_question(payload)
        model = _extract_model(payload)
        if not question:
            return _json_error("ASK_TIMEOUT", "question is required", status_code=400)

        client_ip = _resolve_client_ip(request, settings)
        decision = limiter.try_acquire(client_ip)
        if not decision.allowed:
            return _rate_limited_response(decision.retry_after_seconds or 1)

        worker = pool.try_acquire()
        if worker is None:
            limiter.release(client_ip)
            return _busy_response()

        return StreamingResponse(
            _build_stream(
                worker=worker,
                pool_manager=pool,
                rate_limiter=limiter,
                client_ip=client_ip,
                question=question,
                model=model,
            ),
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

    pool_manager = WorkerPoolManager(
        template_settings=service.settings,
        worker_count=workers if workers is not None else service.settings.ui_worker_count,
    )
    pool_manager.seed_profiles_from(service.settings)
    app = create_chat_ui_app(service=service, pool_manager=pool_manager)

    threading.Thread(target=pool_manager.refresh_all, daemon=True).start()

    browser_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    url = f"http://{browser_host}:{port}/"
    print(f"ui running: {url}")
    if open_browser:
        webbrowser.open(url)

    uvicorn.run(app, host=host, port=port, log_level="warning")
    return 0
