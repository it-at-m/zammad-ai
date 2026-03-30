"""Top-level settings for the Zammad AI index job."""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import (
    BaseSettings,
    CliSettingsSource,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

from .genai import GenAISettings
from .index import IndexJobSettings
from .logging import LoggingSettings
from .qdrant import QdrantSettings
from .zammad import ZammadAPISettings, ZammadEAISettings


def _is_test_mode() -> bool:
    """Check if settings are loaded in a test context.

    YAML should only be disabled for pytest runs or when explicitly requested.
    """
    import os

    if os.getenv("PYTEST_CURRENT_TEST"):
        return True

    if os.getenv("ZAMMAD_AI_DISABLE_YAML", "").lower() in {"1", "true", "yes"}:
        return True

    return False


def _should_enable_cli() -> bool:
    """Check if CLI parsing should be enabled based on sys.argv."""
    import sys

    if "pytest" in sys.modules:
        return False

    argv_str = " ".join(sys.argv).lower()
    test_indicators = ["pytest", "py.test", "unittest"]
    return not any(indicator in argv_str for indicator in test_indicators)


class ZammadAIIndexSettings(BaseSettings):
    """Application settings for the index job.

    This class aggregates all configuration settings for the application, including GenAI, Zammad, Qdrant, logging, and index settings.
    """

    index: IndexJobSettings = Field(
        description="Settings for the indexing job, including configuration for fetching and processing knowledge base answers.",
        default_factory=lambda: IndexJobSettings(),
    )

    genai: GenAISettings = Field(
        description="Settings for GenAI integration, including model selection and configuration.",
        default_factory=lambda: GenAISettings(),
    )

    zammad: ZammadAPISettings | ZammadEAISettings = Field(
        description="Settings for Zammad integration, including API details and knowledge base configuration.",
        discriminator="type",
    )

    log: LoggingSettings = Field(
        description="Settings for logging configuration, including format selection.",
        default_factory=lambda: LoggingSettings(),
    )

    qdrant: QdrantSettings = Field(
        description="Settings for Qdrant vector database integration, including host URL, API key, collection name, and vector configuration.",
        default_factory=lambda: QdrantSettings(),
    )

    langfuse_enabled: bool = Field(
        description="Whether to enable Langfuse integration for logging and prompt fetching.",
        default=True,
    )
    mode: Literal["production", "development", "unittest"] = Field(
        description="Application mode, affecting logging and other behavior.",
        default="production",
    )

    model_config = SettingsConfigDict(
        env_prefix="ZAMMAD_AI_",
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        env_nested_delimiter="__",
        nested_model_default_partial_update=True,
        yaml_file="config.yaml",
        yaml_file_encoding="utf-8",
        cli_parse_args=_should_enable_cli(),
        cli_kebab_case=True,
        cli_prog_name="zammad-ai",
        extra="ignore",
    )

    # Settings sources in order of priority (first = highest priority):

    # 1. CLI args, 2. Environment variables, 3. .env file, 4. YAML config

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Define the precedence and ordering of configuration sources for the settings class.

        The returned tuple lists settings sources in precedence order (highest priority first): initialization values, CLI arguments (if enabled), environment variables, dotenv (.env) file, and YAML configuration file.

        Returns:
            tuple[PydanticBaseSettingsSource, ...]: Settings sources in priority order.
        """
        sources = [init_settings]

        # Only add CLI source if CLI parsing is enabled
        if _should_enable_cli():
            sources.append(CliSettingsSource(settings_cls))

        sources.extend([env_settings, dotenv_settings])

        if _is_test_mode():
            sources.append(YamlConfigSettingsSource(settings_cls, yaml_file=[]))
        else:
            sources.append(YamlConfigSettingsSource(settings_cls))

        return tuple(sources)


@lru_cache(maxsize=1)
def get_settings() -> ZammadAIIndexSettings:
    """Provide the application's cached settings.

    Returns:
        ZammadAIIndexSettings: The cached settings instance used by the application.
    """
    return ZammadAIIndexSettings()  # type: ignore
