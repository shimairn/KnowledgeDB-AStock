from __future__ import annotations

from fastapi import FastAPI

from ima_bridge.schemas import AskRequest, AskResponse, HealthResponse
from ima_bridge.service import IMABridgeService


def create_app() -> FastAPI:
    service = IMABridgeService()
    app = FastAPI(title="ima 爱分享桥接", version="0.1.0")

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return service.health()

    @app.post("/ask", response_model=AskResponse)
    def ask(request: AskRequest) -> AskResponse:
        return service.ask_once(request.question)

    return app
