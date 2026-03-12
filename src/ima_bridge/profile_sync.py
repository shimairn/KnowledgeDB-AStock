from __future__ import annotations

import shutil
from pathlib import Path

from ima_bridge.config import Settings
from ima_bridge.utils import get_logger

logger = get_logger("ima_bridge.profile_sync")

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

    cloned = clone_profile_dir(source.web_profile_dir, target.web_profile_dir)
    # Target URL state is a small file (not inside profile dir). Sync it even if
    # the profile directory is locked by an existing browser process.
    synced_target = sync_target_state(source.target_url_state_path, target.target_url_state_path)
    return cloned or synced_target


def has_profile_state(profile_dir: Path) -> bool:
    if not profile_dir.exists():
        return False
    return any(path.is_file() for path in profile_dir.rglob("*"))


def clone_profile_dir(source_dir: Path, target_dir: Path) -> bool:
    source = source_dir.resolve()
    target = target_dir.resolve()
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
        # On Windows, an in-use profile directory can fail to delete due to locks.
        # Treat this as a no-op instead of crashing UI startup.
        if target.exists():
            logger.warning(
                "profile seed skipped: target dir still exists (likely locked). target=%s",
                str(target),
            )
            return False
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copytree(source, target, ignore=_ignore_transient)
    except FileExistsError:
        return False
    return True


def sync_target_state(source_path: Path, target_path: Path) -> bool:
    if not source_path.exists():
        existed = target_path.exists()
        target_path.unlink(missing_ok=True)
        return existed
    target_path.parent.mkdir(parents=True, exist_ok=True)
    next_value = source_path.read_text(encoding="utf-8")
    if target_path.exists() and target_path.read_text(encoding="utf-8") == next_value:
        return False
    target_path.write_text(next_value, encoding="utf-8")
    return True


def _ignore_transient(_directory: str, names: list[str]) -> set[str]:
    ignored = {name for name in names if name in _TRANSIENT_NAMES}
    ignored.update(name for name in names if name in _TRANSIENT_DIR_NAMES)
    ignored.update(name for name in names if name.endswith('.lock'))
    return ignored
