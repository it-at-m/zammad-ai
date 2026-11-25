"""Top-level settings for the Zammad AI index job."""

from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Literal

from pydantic import Field, model_validator
from pydantic_settings import (
    BaseSettings,
    CliSettingsSource,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

from .genai import GenAISettings
from .index import IndexJobSettings
from .law import LawConfig
from .logging import LoggingSettings
from .qdrant import QdrantSettings
from .target import IndexTargetSettings
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

    targets: list[IndexTargetSettings] = Field(
        description=(
            "Indexing targets, e.g. one per usecase. At least one target is required. Each target is "
            "indexed into its own Qdrant collection, inherits unspecified qdrant and zammad fields from "
            "the root configuration, and defines its own laws. Every target must resolve to a "
            "collection_name and a knowledge_base_id."
        ),
        default_factory=list,
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

    @model_validator(mode="after")
    def _validate_unique_target_names(self) -> "ZammadAIIndexSettings":
        """Ensure no duplicate target names are configured."""
        names = [target.name for target in self.targets]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise ValueError(f"Duplicate target names in settings: {', '.join(duplicates)}")
        return self

    def resolve_targets(self) -> list["ResolvedTarget"]:
        """Resolve one effective settings object and law list per indexing target.

        At least one target is required; root-level laws are ignored and must
        be defined per target instead. Each target deep-merges its qdrant and
        zammad overrides into the root configuration, so shared settings such
        as the Qdrant URL or Zammad base URL stay configured once. Raises a
        ValueError when a target is missing its collection or knowledge base,
        or when two targets resolve to the same collection.
        """
        if not self.targets:
            raise ValueError("At least one indexing target must be configured under 'targets'.")
        resolved: list[ResolvedTarget] = []
        collection_names: list[str] = []
        for target in self.targets:
            payload: dict[str, Any] = self.model_dump(mode="python", exclude={"targets"})
            _deep_merge(payload, {"qdrant": target.qdrant, "zammad": target.zammad})
            effective = ZammadAIIndexSettings.model_validate(payload)
            collection_name = effective.qdrant.collection_name
            knowledge_base_id = effective.zammad.knowledge_base_id
            missing: list[str] = []
            if collection_name is None:
                missing.append("qdrant.collection_name")
            if knowledge_base_id is None:
                missing.append("zammad.knowledge_base_id")
            if missing:
                raise ValueError(f"Target '{target.name}' is missing: {', '.join(missing)}")
            assert collection_name is not None and knowledge_base_id is not None
            resolved.append(ResolvedTarget(name=target.name, settings=effective, laws=target.laws))
            collection_names.append(collection_name)
        duplicates = sorted({name for name in collection_names if collection_names.count(name) > 1})
        if duplicates:
            raise ValueError(f"Targets must resolve to unique Qdrant collections: {', '.join(duplicates)}")
        return resolved


@dataclass(frozen=True)
class ResolvedTarget:
    """One resolved indexing target with its effective settings and laws."""

    name: str
    settings: ZammadAIIndexSettings
    laws: list[LawConfig]


def _deep_merge(target: dict[str, Any], override: dict[str, Any]) -> None:
    """Recursively merge the override mapping into the target mapping."""
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_merge(target[key], value)
        else:
            target[key] = value


@lru_cache(maxsize=1)
def get_settings() -> ZammadAIIndexSettings:
    """Provide the application's cached settings.

    Returns:
        ZammadAIIndexSettings: The cached settings instance used by the application.
    """
    return ZammadAIIndexSettings()
