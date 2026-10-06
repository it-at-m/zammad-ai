"""Tests for application settings loading behavior."""

from typing import Literal

import pytest
from pydantic import SecretStr, ValidationError

from app.settings.api import APISettings
from app.settings.frontend import FeedbackSettings
from app.settings.polling import PollingSettings
from app.settings.settings import ZammadAISettings, get_settings


def test_feedback_settings_require_salt_for_internal_notes() -> None:
    """Feedback links posted internally must use a per-link token salt."""
    with pytest.raises(ValidationError, match="salt must be configured"):
        FeedbackSettings(post_internal_note=True)


@pytest.mark.parametrize(
    ("post_internal_note", "salt"),
    [(False, None), (False, "secret"), (True, "secret")],
)
def test_feedback_settings_accept_valid_internal_note_configurations(
    post_internal_note: bool, salt: SecretStr | None
) -> None:
    """Feedback settings should retain all supported configurations."""
    settings = FeedbackSettings(post_internal_note=post_internal_note, salt=salt)

    assert settings.post_internal_note is post_internal_note
    assert settings.salt is None or settings.salt.get_secret_value() == salt


@pytest.mark.parametrize("language", ["de", "en"])
def test_feedback_settings_accept_supported_languages(language: Literal["de", "en"]) -> None:
    """Feedback settings should accept each provided translation catalog."""
    assert FeedbackSettings(language=language).language == language


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


def test_api_shutdown_timeout_defaults_to_10_seconds() -> None:
    """Limit the wait for browser connections during graceful shutdown."""
    assert APISettings().shutdown_timeout_seconds == 10


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


def test_polling_settings_defaults() -> None:
    """PollingSettings should provide safe defaults with polling disabled."""
    settings = PollingSettings()

    assert settings.enabled is False
    assert settings.interval_seconds == 60
    assert settings.search_query == "state.name:(new OR open)"
    assert settings.processed_ttl_seconds == 3600
    assert settings.per_page == 50
    assert settings.max_pages == 1


@pytest.mark.parametrize("value", [0, 201, -1])
def test_polling_settings_rejects_out_of_range_per_page(value: int) -> None:
    """PollingSettings should reject per_page values outside 1..200."""
    with pytest.raises(ValidationError):
        PollingSettings(per_page=value)


def test_polling_settings_rejects_non_positive_interval() -> None:
    """PollingSettings should reject a non-positive polling interval."""
    with pytest.raises(ValidationError):
        PollingSettings(interval_seconds=0)


def test_polling_settings_rejects_non_positive_max_pages() -> None:
    """PollingSettings should reject a non-positive page limit."""
    with pytest.raises(ValidationError):
        PollingSettings(max_pages=0)


def test_polling_settings_rejects_non_positive_ttl() -> None:
    """PollingSettings should reject a non-positive deduplication TTL."""
    with pytest.raises(ValidationError):
        PollingSettings(processed_ttl_seconds=0)


def test_zammad_ai_settings_includes_polling_defaults() -> None:
    """ZammadAISettings should include polling settings and default to disabled."""
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.polling.enabled is False
