from __future__ import annotations

from ima_bridge.config import get_settings, is_loopback_host, resolve_port, sanitize_instance


def test_settings_create_dirs(tmp_path, monkeypatch):
    monkeypatch.setenv("IMA_MANAGED_PROFILE_DIR", str(tmp_path / "profile"))
    monkeypatch.setenv("IMA_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("IMA_WEB_PROFILE_DIR", str(tmp_path / "web-profile"))
    settings = get_settings()
    assert settings.managed_profile_dir.exists()
    assert settings.web_profile_dir.exists()
    assert settings.screenshots_dir.exists()
    assert settings.runtime_dir.exists()
    assert str(settings.target_url_state_path).endswith(f"target-url-{settings.instance}.txt")


def test_instance_specific_settings(tmp_path, monkeypatch):
    monkeypatch.delenv("IMA_MANAGED_PROFILE_DIR", raising=False)
    monkeypatch.delenv("IMA_WEB_PROFILE_DIR", raising=False)
    monkeypatch.setenv("IMA_MANAGED_PROFILE_ROOT", str(tmp_path / "profiles"))
    monkeypatch.setenv("IMA_WEB_PROFILE_ROOT", str(tmp_path / "web-profiles"))
    monkeypatch.setenv("IMA_APP_CDP_PORT_BASE", "9400")
    settings = get_settings(instance="window-2")
    assert settings.instance == "window-2"
    assert settings.app_cdp_port != 9400
    assert "ima-managed-window-2" in str(settings.managed_profile_dir)
    assert str(settings.web_profile_dir).endswith("web-profiles\\window-2")


def test_resolve_port_respects_explicit(monkeypatch):
    monkeypatch.setenv("IMA_APP_CDP_PORT_BASE", "9228")
    assert resolve_port("abc", 9555) == 9555
    assert resolve_port(sanitize_instance("default"), None) == 9228


def test_get_settings_can_override_driver_mode_and_headless():
    settings = get_settings(driver_mode="web", web_headless=False)
    assert settings.driver_mode == "web"
    assert settings.web_headless is False


def test_get_settings_reads_ui_env(monkeypatch):
    monkeypatch.setenv("IMA_UI_WORKER_COUNT", "7")
    monkeypatch.setenv("IMA_UI_RATE_LIMIT_PER_MINUTE", "15")
    monkeypatch.setenv("IMA_UI_MAX_CONCURRENT_PER_IP", "3")
    monkeypatch.setenv("IMA_UI_TRUST_PROXY", "1")

    settings = get_settings()

    assert settings.ui_worker_count == 7
    assert settings.ui_rate_limit_per_minute == 15
    assert settings.ui_max_concurrent_per_ip == 3
    assert settings.ui_trust_proxy is True


def test_is_loopback_host():
    assert is_loopback_host("127.0.0.1") is True
    assert is_loopback_host("localhost") is True
    assert is_loopback_host("::1") is True
    assert is_loopback_host("0.0.0.0") is False

