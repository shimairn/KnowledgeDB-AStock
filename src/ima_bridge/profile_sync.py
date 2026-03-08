from __future__ import annotations

import shutil
from pathlib import Path

from ima_bridge.config import Settings

_TRANSIENT_NAMES = {
    "SingletonCookie",
    "SingletonLock",
    "SingletonSocket",
    "DevToolsActivePort",
    "lockfile",
}
_TRANSIENT_DIR_NAMES = {
    "Crashpad",
    "Code Cache",
    "GPUCache",
    "GrShaderCache",
    "ShaderCache",
}


def sync_profile_state(source: Settings, target: Settings) -> bool:
    if source.web_profile_dir.resolve() == target.web_profile_dir.resolve():
        return False
    if not has_profile_state(source.web_profile_dir):
        return False

    clone_profile_dir(source.web_profile_dir, target.web_profile_dir)
    sync_target_state(source.target_url_state_path, target.target_url_state_path)
    return True


def has_profile_state(profile_dir: Path) -> bool:
    if not profile_dir.exists():
        return False
    return any(path.is_file() for path in profile_dir.rglob("*"))


def clone_profile_dir(source_dir: Path, target_dir: Path) -> None:
    source = source_dir.resolve()
    target = target_dir.resolve()
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target, ignore=_ignore_transient)


def sync_target_state(source_path: Path, target_path: Path) -> None:
    if not source_path.exists():
        target_path.unlink(missing_ok=True)
        return
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(source_path.read_text(encoding="utf-8"), encoding="utf-8")


def _ignore_transient(_directory: str, names: list[str]) -> set[str]:
    ignored = {name for name in names if name in _TRANSIENT_NAMES}
    ignored.update(name for name in names if name in _TRANSIENT_DIR_NAMES)
    ignored.update(name for name in names if name.endswith('.lock'))
    return ignored
