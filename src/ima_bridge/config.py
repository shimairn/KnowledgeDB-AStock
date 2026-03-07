from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    kb_name: str = field(default_factory=lambda: os.getenv("IMA_KB_NAME", "爱分享"))
    kb_owner: str = field(default_factory=lambda: os.getenv("IMA_KB_OWNER", "购物小助手"))
    kb_title: str = field(default_factory=lambda: os.getenv("IMA_KB_TITLE", "【爱分享】的财经资讯"))
    app_window_title: str = field(
        default_factory=lambda: os.getenv("IMA_APP_WINDOW_TITLE", "【爱分享】的财经资讯 - ima.copilot")
    )
    mode: str = field(default_factory=lambda: os.getenv("IMA_MODE", "对话模式"))
    model: str = field(default_factory=lambda: os.getenv("IMA_MODEL", "DS V3.2"))
    default_question: str = field(
        default_factory=lambda: os.getenv(
            "IMA_DEFAULT_QUESTION",
            "请概括这个知识库的主要栏目，并说明各自关注点。",
        )
    )
    web_home_url: str = field(default_factory=lambda: os.getenv("IMA_WEB_HOME_URL", "https://ima.qq.com/"))
    web_wikis_url: str = field(default_factory=lambda: os.getenv("IMA_WEB_WIKIS_URL", "https://ima.qq.com/wikis"))
    login_wait_seconds: int = field(default_factory=lambda: int(os.getenv("IMA_LOGIN_WAIT_SECONDS", "180")))
    answer_timeout_seconds: int = field(default_factory=lambda: int(os.getenv("IMA_ANSWER_TIMEOUT_SECONDS", "120")))
    answer_poll_seconds: float = field(default_factory=lambda: float(os.getenv("IMA_ANSWER_POLL_SECONDS", "2")))
    headless: bool = field(default_factory=lambda: os.getenv("IMA_HEADLESS", "0") == "1")
    output_root: Path = field(default_factory=lambda: Path(os.getenv("IMA_OUTPUT_ROOT", "output/playwright")))

    @property
    def screenshot_dir(self) -> Path:
        return self.output_root / "screenshots"

    @property
    def browser_profile_dir(self) -> Path:
        return self.output_root / "profiles" / "msedge"


def get_settings() -> Settings:
    settings = Settings()
    settings.output_root.mkdir(parents=True, exist_ok=True)
    settings.screenshot_dir.mkdir(parents=True, exist_ok=True)
    settings.browser_profile_dir.mkdir(parents=True, exist_ok=True)
    return settings
