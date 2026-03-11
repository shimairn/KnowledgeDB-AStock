from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from ima_bridge.profile_sync import clone_profile_dir, sync_target_state


def test_clone_profile_dir_returns_false_when_target_cannot_be_removed(tmp_path, monkeypatch):
    source = tmp_path / "source"
    target = tmp_path / "target"
    (source / "Default").mkdir(parents=True)
    (source / "Default" / "Preferences").write_text("{}", encoding="utf-8")
    target.mkdir(parents=True)

    def fake_rmtree(_path, ignore_errors=False):
        # Simulate a locked directory: rmtree does nothing but also does not raise.
        return None

    monkeypatch.setattr(shutil, "rmtree", fake_rmtree)

    assert clone_profile_dir(source, target) is False
    assert (target / "Default" / "Preferences").exists() is False


def test_sync_target_state_is_idempotent(tmp_path):
    source = tmp_path / "source.txt"
    target = tmp_path / "target.txt"
    source.write_text("hello", encoding="utf-8")

    assert sync_target_state(source, target) is True
    assert sync_target_state(source, target) is False

