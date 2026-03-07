from __future__ import annotations

import pytest

from ima_bridge.config import Settings


@pytest.fixture
def settings_fixture(tmp_path):
    settings = Settings(output_root=tmp_path / "output")
    settings.output_root.mkdir(parents=True, exist_ok=True)
    settings.screenshot_dir.mkdir(parents=True, exist_ok=True)
    settings.browser_profile_dir.mkdir(parents=True, exist_ok=True)
    return settings
