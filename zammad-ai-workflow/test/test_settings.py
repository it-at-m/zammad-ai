"""Tests for application settings loading behavior."""

import pytest
from app.settings.settings import ZammadAISettings, get_settings
from pydantic import ValidationError


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


def test_max_user_text_length_defaults_to_2000() -> None:
    """Settings should default max user text length to 2000 characters."""
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.max_user_text_length == 2000


@pytest.mark.parametrize("value", [1, 100, 4096])
def test_max_user_text_length_accepts_supported_values(monkeypatch, value: int) -> None:
    """Settings should accept configured PositiveInt."""
    monkeypatch.setenv("ZAMMAD_AI_MAX_USER_TEXT_LENGTH", str(value))
    get_settings.cache_clear()
    try:
        settings = get_settings()
    finally:
        get_settings.cache_clear()
        monkeypatch.delenv("ZAMMAD_AI_MAX_USER_TEXT_LENGTH", raising=False)

    assert settings.max_user_text_length == value


@pytest.mark.parametrize("value", [0, -1, -100])
def test_max_user_text_length_rejects_non_positive_int(monkeypatch, value: int) -> None:
    """Settings should reject non positive values."""
    monkeypatch.setenv("ZAMMAD_AI_MAX_USER_TEXT_LENGTH", str(value))
    get_settings.cache_clear()
    try:
        with pytest.raises(ValidationError):
            get_settings()
    finally:
        get_settings.cache_clear()
        monkeypatch.delenv("ZAMMAD_AI_MAX_USER_TEXT_LENGTH", raising=False)
