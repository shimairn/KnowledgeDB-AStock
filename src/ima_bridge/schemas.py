from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from ima_bridge.utils import now_iso


class KnowledgeBaseIdentity(BaseModel):
    name: str
    owner: str
    title: str


class AskResponse(BaseModel):
    ok: bool
    question: str
    knowledge_base: KnowledgeBaseIdentity
    mode: str
    model: str
    source_driver: Literal["app", "web"] = "web"
    answer_text: str = ""
    answer_html: str = ""
    references: list[str] = Field(default_factory=list)
    screenshot_path: str | None = None
    captured_at: str = Field(default_factory=now_iso)
    error_code: str | None = None
    error_message: str | None = None


class HealthResponse(BaseModel):
    ok: bool
    instance: str
    source_driver: Literal["app", "web"]
    cdp_port: int | None = None
    cdp_endpoint: str | None = None
    cdp_ready: bool | None = None
    base_url: str | None = None
    profile_dir: str | None = None
    headless: bool | None = None
    app_executable: str | None = None
    managed_profile_dir: str
    error_code: str | None = None
    error_message: str | None = None


class LoginResponse(BaseModel):
    ok: bool
    instance: str
    source_driver: Literal["web"] = "web"
    base_url: str
    profile_dir: str
    timeout_seconds: float
    captured_at: str = Field(default_factory=now_iso)
    error_code: str | None = None
    error_message: str | None = None
