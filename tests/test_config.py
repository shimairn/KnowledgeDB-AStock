from __future__ import annotations

from ima_bridge.config import get_settings, resolve_port, sanitize_instance


def test_settings_create_dirs(tmp_path, monkeypatch):
    monkeypatch.setenv("IMA_MANAGED_PROFILE_DIR", str(tmp_path / "profile"))
    monkeypatch.setenv("IMA_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    settings = get_settings()
    assert settings.managed_profile_dir.exists()
    assert settings.screenshots_dir.exists()


def test_instance_specific_settings(tmp_path, monkeypatch):
    monkeypatch.delenv("IMA_MANAGED_PROFILE_DIR", raising=False)
    monkeypatch.setenv("IMA_MANAGED_PROFILE_ROOT", str(tmp_path / "profiles"))
    monkeypatch.setenv("IMA_APP_CDP_PORT_BASE", "9400")
    settings = get_settings(instance="window-2")
    assert settings.instance == "window-2"
    assert settings.app_cdp_port != 9400
    assert "ima-managed-window-2" in str(settings.managed_profile_dir)


def test_resolve_port_respects_explicit(monkeypatch):
    monkeypatch.setenv("IMA_APP_CDP_PORT_BASE", "9228")
    assert resolve_port("abc", 9555) == 9555
    assert resolve_port(sanitize_instance("default"), None) == 9228
