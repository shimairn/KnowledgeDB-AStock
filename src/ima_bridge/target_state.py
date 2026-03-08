from __future__ import annotations

from pathlib import Path
from typing import Callable
from urllib.parse import urlparse


class TargetStateStore:
    def __init__(self, path: Path, base_url: str, generic_paths: set[str]) -> None:
        self.path = path
        self.base_url = base_url.rstrip("/") + "/"
        self.generic_paths = generic_paths

    def load(self) -> str | None:
        if not self.path.exists():
            return None
        value = self.path.read_text(encoding="utf-8").strip()
        if not value.startswith(self.base_url):
            return None
        return value

    def clear(self) -> None:
        if self.path.exists():
            self.path.unlink(missing_ok=True)

    def remember(self, url: str, body_text: str, validator: Callable[[str], bool]) -> bool:
        if not self.can_persist(url, body_text, validator):
            return False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(url, encoding="utf-8")
        return True

    def can_persist(self, url: str, body_text: str, validator: Callable[[str], bool]) -> bool:
        normalized = (url or "").strip()
        if not normalized.startswith(self.base_url):
            return False
        parsed = urlparse(normalized)
        path = parsed.path.rstrip("/")
        if path in self.generic_paths:
            return False
        return validator(body_text)
