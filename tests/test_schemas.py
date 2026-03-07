from ima_bridge.config import get_settings


def test_settings_create_output_dirs(tmp_path, monkeypatch):
    monkeypatch.setenv("IMA_OUTPUT_ROOT", str(tmp_path / "playwright"))
    settings = get_settings()
    assert settings.output_root.exists()
    assert settings.browser_profile_dir.exists()
    assert settings.screenshot_dir.exists()
