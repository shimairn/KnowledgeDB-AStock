from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path


def get_logger(name: str) -> logging.Logger:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    return logging.getLogger(name)


def timestamp_slug() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def ensure_parent(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    return path
