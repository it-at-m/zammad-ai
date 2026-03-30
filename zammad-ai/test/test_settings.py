"""Tests for application settings loading behavior."""

from app.settings.settings import ZammadAISettings, get_settings


def test_get_settings_ignores_local_yaml_in_unittest_mode(tmp_path, monkeypatch) -> None:
    """Settings loading should ignore a broken YAML file in unittest mode."""
    broken_yaml = tmp_path / "config.yaml"
    broken_yaml.write_text("triage: [", encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ZAMMAD_AI_MODE", "unittest")
    monkeypatch.setenv("ZAMMAD_AI_DISABLE_YAML", "1")

    get_settings.cache_clear()
    try:
        settings: ZammadAISettings = get_settings()
    finally:
        get_settings.cache_clear()

    assert settings.mode == "unittest"
    assert settings.triage.prompts.type == "string"
