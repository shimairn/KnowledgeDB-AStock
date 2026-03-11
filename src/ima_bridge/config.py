from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

DEFAULT_INSTANCE: Final[str] = "default"
DEFAULT_PORT: Final[int] = 9228
MAX_INSTANCE_OFFSET: Final[int] = 400


@dataclass(frozen=True)
class Settings:
    kb_name: str = field(default_factory=lambda: os.getenv("IMA_KB_NAME", "\u7231\u5206\u4eab"))
    kb_owner: str = field(default_factory=lambda: os.getenv("IMA_KB_OWNER", "\u8d2d\u7269\u5c0f\u52a9\u624b"))
    kb_title: str = field(default_factory=lambda: os.getenv("IMA_KB_TITLE", "\u3010\u7231\u5206\u4eab\u3011\u7684\u8d22\u7ecf\u8d44\u8baf"))
    # UI-only label (does not affect KB matching/selection in the driver).
    kb_label: str = field(default_factory=lambda: os.getenv("IMA_KB_LABEL", "\u8d22\u7ecf\u77e5\u8bc6\u5e93"))
    mode_name: str = field(default_factory=lambda: os.getenv("IMA_MODE_NAME", "\u5bf9\u8bdd\u6a21\u5f0f"))
    model_prefix: str = field(default_factory=lambda: os.getenv("IMA_MODEL_PREFIX", "DS V3.2 T"))

    driver_mode: str = field(default_factory=lambda: os.getenv("IMA_DRIVER_MODE", "web"))
    app_executable: str | None = field(default_factory=lambda: os.getenv("IMA_APP_EXECUTABLE"))
    instance: str = DEFAULT_INSTANCE
    app_cdp_port: int = DEFAULT_PORT
    managed_profile_dir: Path = field(default_factory=lambda: Path("output/playwright/profiles/ima-managed-default"))

    web_base_url: str = field(default_factory=lambda: os.getenv("IMA_WEB_BASE_URL", "https://ima.qq.com/"))
    web_channel: str | None = field(default_factory=lambda: os.getenv("IMA_WEB_CHANNEL", "msedge"))
    web_headless: bool = field(default_factory=lambda: os.getenv("IMA_WEB_HEADLESS", "1") == "1")
    web_profile_dir: Path = field(default_factory=lambda: Path("output/playwright/web-profiles/default"))
    web_navigation_timeout_seconds: float = field(
        default_factory=lambda: float(os.getenv("IMA_WEB_NAV_TIMEOUT_SECONDS", "45"))
    )

    artifacts_dir: Path = field(default_factory=lambda: Path(os.getenv("IMA_ARTIFACTS_DIR", "output/playwright")))
    startup_timeout_seconds: float = field(default_factory=lambda: float(os.getenv("IMA_STARTUP_TIMEOUT_SECONDS", "30")))
    login_timeout_seconds: float = field(default_factory=lambda: float(os.getenv("IMA_LOGIN_TIMEOUT_SECONDS", "180")))
    ask_timeout_seconds: float = field(default_factory=lambda: float(os.getenv("IMA_ASK_TIMEOUT_SECONDS", "120")))
    poll_interval_seconds: float = field(default_factory=lambda: float(os.getenv("IMA_POLL_INTERVAL_SECONDS", "1.0")))
    capture_screenshot: bool = field(default_factory=lambda: os.getenv("IMA_CAPTURE_SCREENSHOT", "0") == "1")
    ui_worker_count: int = field(default_factory=lambda: int(os.getenv("IMA_UI_WORKER_COUNT", "10")))
    ui_rate_limit_per_minute: int = field(default_factory=lambda: int(os.getenv("IMA_UI_RATE_LIMIT_PER_MINUTE", "12")))
    ui_max_concurrent_per_ip: int = field(default_factory=lambda: int(os.getenv("IMA_UI_MAX_CONCURRENT_PER_IP", "2")))
    ui_trust_proxy: bool = field(default_factory=lambda: os.getenv("IMA_UI_TRUST_PROXY", "0") == "1")
    output_gc_enabled: bool = field(default_factory=lambda: os.getenv("IMA_OUTPUT_GC_ENABLED", "1") == "1")
    output_gc_interval_seconds: float = field(default_factory=lambda: float(os.getenv("IMA_OUTPUT_GC_INTERVAL_SECONDS", "1800")))
    output_gc_retention_hours: float = field(default_factory=lambda: float(os.getenv("IMA_OUTPUT_GC_RETENTION_HOURS", "24")))
    output_gc_include_profiles: bool = field(default_factory=lambda: os.getenv("IMA_OUTPUT_GC_INCLUDE_PROFILES", "0") == "1")

    @property
    def cdp_endpoint(self) -> str:
        return f"http://127.0.0.1:{self.app_cdp_port}"

    @property
    def screenshots_dir(self) -> Path:
        return self.artifacts_dir / "screenshots" / self.instance

    @property
    def runtime_dir(self) -> Path:
        return self.artifacts_dir / "runtime"

    @property
    def target_url_state_path(self) -> Path:
        return self.runtime_dir / f"target-url-{self.instance}.txt"


def get_settings(
    instance: str | None = None,
    port: int | None = None,
    profile_dir: str | None = None,
    driver_mode: str | None = None,
    web_headless: bool | None = None,
) -> Settings:
    selected_instance = sanitize_instance(instance or os.getenv("IMA_INSTANCE", DEFAULT_INSTANCE))
    selected_port = resolve_port(selected_instance, port)
    selected_profile = resolve_profile_dir(selected_instance, profile_dir)
    selected_web_profile = resolve_web_profile_dir(selected_instance)
    settings = Settings(
        instance=selected_instance,
        app_cdp_port=selected_port,
        managed_profile_dir=selected_profile,
        web_profile_dir=selected_web_profile,
        driver_mode=driver_mode or os.getenv("IMA_DRIVER_MODE", "web"),
        web_headless=(web_headless if web_headless is not None else os.getenv("IMA_WEB_HEADLESS", "1") == "1"),
    )
    settings.managed_profile_dir.mkdir(parents=True, exist_ok=True)
    settings.web_profile_dir.mkdir(parents=True, exist_ok=True)
    settings.screenshots_dir.mkdir(parents=True, exist_ok=True)
    settings.runtime_dir.mkdir(parents=True, exist_ok=True)
    return settings


def sanitize_instance(value: str) -> str:
    compact = "".join(ch.lower() if ch.isalnum() else "-" for ch in value.strip())
    compact = "-".join(part for part in compact.split("-") if part)
    return compact or DEFAULT_INSTANCE


def resolve_port(instance: str, explicit_port: int | None) -> int:
    if explicit_port is not None:
        return explicit_port
    env_port = os.getenv("IMA_APP_CDP_PORT")
    if env_port:
        return int(env_port)

    base = int(os.getenv("IMA_APP_CDP_PORT_BASE", str(DEFAULT_PORT)))
    if instance == DEFAULT_INSTANCE:
        return base

    offset = sum(ord(ch) for ch in instance) % MAX_INSTANCE_OFFSET
    if offset == 0:
        offset = 1
    return base + offset


def resolve_profile_dir(instance: str, explicit_profile_dir: str | None) -> Path:
    if explicit_profile_dir:
        return Path(explicit_profile_dir)
    direct = os.getenv("IMA_MANAGED_PROFILE_DIR")
    if direct:
        return Path(direct)
    root = Path(os.getenv("IMA_MANAGED_PROFILE_ROOT", "output/playwright/profiles"))
    return root / f"ima-managed-{instance}"


def resolve_web_profile_dir(instance: str) -> Path:
    direct = os.getenv("IMA_WEB_PROFILE_DIR")
    if direct:
        return Path(direct)
    root = Path(os.getenv("IMA_WEB_PROFILE_ROOT", "output/playwright/web-profiles"))
    return root / instance


def is_loopback_host(host: str) -> bool:
    normalized = (host or "").strip().lower()
    return normalized in {"127.0.0.1", "localhost", "::1"}

