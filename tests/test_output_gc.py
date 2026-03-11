from __future__ import annotations

import os
import time
from pathlib import Path

from ima_bridge.output_gc import prune_artifacts_dir


def _touch(path: Path, *, mtime: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x", encoding="utf-8")
    os.utime(path, (mtime, mtime))


def test_prune_artifacts_dir_removes_old_files_and_empty_dirs(tmp_path):
    root = tmp_path / "artifacts"
    root.mkdir(parents=True, exist_ok=True)

    now = time.time()
    old_mtime = now - 3600
    new_mtime = now - 10

    old_file = root / "old.txt"
    new_file = root / "new.txt"
    nested_old = root / "nested" / "deep" / "old.txt"

    _touch(old_file, mtime=old_mtime)
    _touch(nested_old, mtime=old_mtime)
    _touch(new_file, mtime=new_mtime)

    stats = prune_artifacts_dir(root, retention_seconds=60, now=now)

    assert not old_file.exists()
    assert not nested_old.exists()
    assert new_file.exists()
    assert not (root / "nested").exists()
    assert stats.removed_files >= 2


def test_prune_artifacts_dir_respects_exclude_dirs(tmp_path):
    root = tmp_path / "artifacts"
    root.mkdir(parents=True, exist_ok=True)

    now = time.time()
    old_mtime = now - 3600

    excluded = root / "web-profiles"
    excluded_old = excluded / "keep.txt"
    other_old = root / "runtime" / "remove.txt"

    _touch(excluded_old, mtime=old_mtime)
    _touch(other_old, mtime=old_mtime)

    stats = prune_artifacts_dir(root, retention_seconds=60, exclude_dirs=[excluded], now=now)

    assert excluded.exists()
    assert excluded_old.exists()
    assert not other_old.exists()
    assert stats.removed_files >= 1

