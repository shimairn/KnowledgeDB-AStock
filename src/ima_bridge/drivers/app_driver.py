from __future__ import annotations

from pathlib import Path

from pywinauto import Desktop

from ima_bridge.config import Settings
from ima_bridge.errors import CaptureFailedError, DriverUnavailableError
from ima_bridge.schemas import DriverHealth, KnowledgeBaseIdentity
from ima_bridge.utils import ensure_parent, get_logger, timestamp_slug

from .base import AskDriver


class AppDriver(AskDriver):
    source_driver = "app"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.logger = get_logger("ima_bridge.app_driver")

    def _connect_window(self):
        try:
            desktop = Desktop(backend="uia")
            return desktop.window(title=self.settings.app_window_title)
        except Exception as exc:
            raise DriverUnavailableError(f"无法连接到 ima App 窗口: {exc}") from exc

    def _collect_visible_text(self, window) -> str:
        texts: list[str] = []
        try:
            for item in window.descendants():
                try:
                    value = item.window_text().strip()
                except Exception:
                    value = ""
                if value:
                    texts.append(value)
        except Exception:
            return ""
        return "\n".join(dict.fromkeys(texts))

    def health(self) -> DriverHealth:
        try:
            window = self._connect_window()
            if not window.exists(timeout=2):
                return DriverHealth(name=self.source_driver, available=False, detail="未检测到目标 ima 窗口")
            return DriverHealth(name=self.source_driver, available=True, detail=f"检测到窗口: {self.settings.app_window_title}")
        except Exception as exc:
            return DriverHealth(name=self.source_driver, available=False, detail=str(exc))

    def ask(self, question: str):
        window = self._connect_window()
        if not window.exists(timeout=2):
            raise DriverUnavailableError("未找到正在运行的 ima App 窗口")
        visible_text = self._collect_visible_text(window)
        screenshot_path = ensure_parent(Path(self.settings.screenshot_dir) / f"app-preflight-{timestamp_slug()}.png")
        try:
            image = window.capture_as_image()
            image.save(str(screenshot_path))
        except Exception as exc:
            self.logger.warning("capture app screenshot failed: %s", exc)
        if self.settings.app_window_title not in window.window_text():
            raise DriverUnavailableError("当前 ima 窗口不是目标知识库页面")
        if visible_text:
            self.logger.info("app visible text collected for diagnostics")
        raise CaptureFailedError(
            f"已检测到 App 目标窗口，但当前 v1 无法稳定从 App 直接抓取回答区 HTML，已生成诊断截图: {screenshot_path}",
            can_fallback=True,
        )

    def kb_identity(self) -> KnowledgeBaseIdentity:
        return KnowledgeBaseIdentity(
            name=self.settings.kb_name,
            owner=self.settings.kb_owner,
            title=self.settings.kb_title,
        )
