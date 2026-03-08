from __future__ import annotations

from pathlib import Path
from typing import Callable
from urllib.parse import urlparse, urlunparse


class TargetStateStore:
    def __init__(self, path: Path, base_url: str, generic_paths: set[str]) -> None:
        self.path = path
        self.base_url = base_url.rstrip("/") + "/"
        self.generic_paths = generic_paths

    def load(self) -> str | None:
        if not self.path.exists():
            return None
        value = self.normalize_url(self.path.read_text(encoding="utf-8"))
        if value is None:
            return None
        if self.path.read_text(encoding="utf-8").strip() != value:
            self.path.write_text(value, encoding="utf-8")
        return value

    def clear(self) -> None:
        if self.path.exists():
            self.path.unlink(missing_ok=True)

    def remember(self, url: str, body_text: str, validator: Callable[[str], bool]) -> bool:
        normalized = self.normalize_url(url)
        if not self.can_persist(normalized, body_text, validator):
            return False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(normalized, encoding="utf-8")
        return True

    def can_persist(self, url: str, body_text: str, validator: Callable[[str], bool]) -> bool:
        normalized = self.normalize_url(url)
        if normalized is None:
            return False
        parsed = urlparse(normalized)
        path = parsed.path.rstrip("/")
        if path in self.generic_paths:
            return False
        return validator(body_text)

    def normalize_url(self, url: str) -> str | None:
        normalized = (url or "").strip()
        if not normalized.startswith(self.base_url):
            return None
        parsed = urlparse(normalized)
        path = parsed.path or "/"
        if path != "/":
            path = path.rstrip("/")
        return urlunparse((parsed.scheme, parsed.netloc, path, "", "", ""))
