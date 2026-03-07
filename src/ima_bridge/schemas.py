from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


class KnowledgeBaseIdentity(BaseModel):
    name: str
    owner: str
    title: str


class ReferenceItem(BaseModel):
    text: str
    href: str | None = None


class AskRequest(BaseModel):
    question: str = Field(min_length=1)


class AskResponse(BaseModel):
    ok: bool
    question: str
    knowledge_base: KnowledgeBaseIdentity
    mode: str
    model: str
    source_driver: Literal["app", "web_fallback"]
    answer_text: str = ""
    answer_html: str = ""
    references: list[ReferenceItem] = Field(default_factory=list)
    screenshot_path: str | None = None
    captured_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    error_code: str | None = None
    error_message: str | None = None


class DriverHealth(BaseModel):
    name: str
    available: bool
    detail: str


class HealthResponse(BaseModel):
    ok: bool
    knowledge_base: KnowledgeBaseIdentity
    mode: str
    model: str
    drivers: list[DriverHealth]
