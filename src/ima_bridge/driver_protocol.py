from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Literal, Protocol

DriverSource = Literal["web", "app"]


@dataclass(frozen=True)
class DriverHealthStatus:
    ok: bool
    source_driver: DriverSource
    error_code: str | None = None
    error_message: str | None = None
    cdp_port: int | None = None
    cdp_endpoint: str | None = None
    cdp_ready: bool | None = None
    base_url: str | None = None
    profile_dir: str | None = None
    headless: bool | None = None
    app_executable: str | None = None
    managed_profile_dir: str | None = None


@dataclass(frozen=True)
class DriverLoginStatus:
    ok: bool
    source_driver: DriverSource = "web"
    base_url: str = ""
    profile_dir: str = ""
    timeout_seconds: float = 0.0
    error_code: str | None = None
    error_message: str | None = None


@dataclass(frozen=True)
class DriverAskResult:
    source_driver: DriverSource
    thinking_text: str = ""
    answer_text: str = ""
    answer_html: str = ""
    references: list[str] = field(default_factory=list)
    screenshot_path: str | None = None


class AskDriver(Protocol):
    source_driver: DriverSource

    def health(self) -> DriverHealthStatus:
        ...

    def login(self, timeout_seconds: float | None = None) -> DriverLoginStatus:
        ...

    def ask(
        self,
        question: str,
        on_update: Callable[..., None] | None = None,
    ) -> DriverAskResult:
        ...
