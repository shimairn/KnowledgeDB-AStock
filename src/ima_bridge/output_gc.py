from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from ima_bridge.utils import get_logger


logger = get_logger("ima_bridge.output_gc")


@dataclass
class OutputGcStats:
    removed_files: int = 0
    removed_dirs: int = 0
    errors: int = 0


def prune_artifacts_dir(
    root_dir: Path,
    *,
    retention_seconds: float,
    exclude_dirs: Iterable[Path] = (),
    now: float | None = None,
) -> OutputGcStats:
    """Best-effort prune of old files under root_dir.

    - Skips anything under exclude_dirs.
    - Only deletes entries older than retention_seconds by mtime.
    - Windows file locks are treated as non-fatal (errors are counted and ignored).
    """

    root = root_dir.resolve()
    if not root.exists():
        return OutputGcStats()

    cutoff = (now if now is not None else time.time()) - max(0.0, float(retention_seconds))
    excludes = [Path(path).resolve() for path in exclude_dirs]
    stats = OutputGcStats()

    def is_excluded(path: Path) -> bool:
        for excluded in excludes:
            try:
                path.relative_to(excluded)
                return True
            except ValueError:
                continue
        return False

    # Delete old files.
    for dirpath, dirnames, filenames in os.walk(root, topdown=True):
        current = Path(dirpath)
        if is_excluded(current):
            dirnames[:] = []
            continue

        # Prevent descending into excluded children.
        kept: list[str] = []
        for name in dirnames:
            child = (current / name)
            if is_excluded(child):
                continue
            kept.append(name)
        dirnames[:] = kept

        for name in filenames:
            path = current / name
            try:
                st = path.stat()
            except OSError:
                stats.errors += 1
                continue

            if st.st_mtime >= cutoff:
                continue

            try:
                path.unlink()
                stats.removed_files += 1
            except OSError:
                stats.errors += 1

    # Remove empty dirs (excluding root), best-effort.
    for dirpath, dirnames, filenames in os.walk(root, topdown=False):
        current = Path(dirpath)
        if current == root or is_excluded(current):
            continue
        # os.walk's dirnames/filenames may be stale if children were removed earlier.
        try:
            next(current.iterdir())
            continue
        except StopIteration:
            pass
        except OSError:
            stats.errors += 1
            continue
        try:
            current.rmdir()
            stats.removed_dirs += 1
        except OSError:
            stats.errors += 1

    return stats


def start_output_gc_thread(
    *,
    root_dir: Path,
    interval_seconds: float,
    retention_seconds: float,
    exclude_dirs: Iterable[Path] = (),
    stop_event: threading.Event | None = None,
) -> tuple[threading.Event, threading.Thread]:
    stop = stop_event or threading.Event()

    def runner() -> None:
        # Run immediately once, then periodically.
        while not stop.is_set():
            stats = prune_artifacts_dir(
                root_dir,
                retention_seconds=retention_seconds,
                exclude_dirs=exclude_dirs,
            )
            if stats.removed_files or stats.removed_dirs:
                logger.info(
                    "output gc: removed_files=%s removed_dirs=%s errors=%s",
                    stats.removed_files,
                    stats.removed_dirs,
                    stats.errors,
                )
            stop.wait(max(5.0, float(interval_seconds)))

    thread = threading.Thread(target=runner, name="ima-output-gc", daemon=True)
    thread.start()
    return stop, thread
