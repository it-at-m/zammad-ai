"""Application settings and configuration source loading."""

from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import Field, PositiveInt, model_validator
from pydantic_settings import (
    BaseSettings,
    CliSettingsSource,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

from .answer import AnswerSettings
from .api import APISettings
from .frontend import FrontendSettings
from .genai import GenAIOpenAISettings, GenAIProviderSettings
from .guardrails import GuardrailSettings
from .kafka import KafkaSettings
from .logging import LoggingSettings
from .polling import PollingSettings
from .preparser import PreparserSettings
from .prometheus import PrometheusSettings
from .triage import TriageSettings
from .usecase import RouterSettings, UseCaseSettings
from .zammad import ZammadAPISettings, ZammadEAISettings


def _is_test_mode() -> bool:
    """Detect whether configuration loading should treat the environment as a test context.

    Returns:
        bool: `True` if the `PYTEST_CURRENT_TEST` environment variable is present or
        if `ZAMMAD_AI_DISABLE_YAML` is set to `"1"`, `"true"`, or `"yes"` (case-insensitive),
        `False` otherwise.
    """
    import os
    import sys

    if os.getenv("PYTEST_CURRENT_TEST"):
        return True

    argv_str = " ".join(sys.argv).lower()
    if "pytest" in sys.modules or any(indicator in argv_str for indicator in ["pytest", "py.test", "unittest"]):
        return True

    if os.getenv("ZAMMAD_AI_DISABLE_YAML", "").lower() in {"1", "true", "yes"}:
        return True

    return False


def _should_enable_cli() -> bool:
    """Determine whether command-line argument parsing should be enabled.

    Returns:
        bool: `True` if no test runner indicators are detected in the environment or argv (allowing CLI parsing), `False` otherwise.
    """
    import sys

    if "pytest" in sys.modules:
        return False

    argv_str = " ".join(sys.argv).lower()
    test_indicators = ["pytest", "py.test", "unittest"]
    return not any(indicator in argv_str for indicator in test_indicators)


class ZammadAISettings(BaseSettings):
    """Application settings for Zammad AI integration.

    This class aggregates all configuration settings for the application, including GenAI, Langfuse, Zammad, Qdrant, Kafka, and triage settings.
    """

    usecase: UseCaseSettings = Field(
        description="Use case settings defining the specific AI application scenario.",
        default_factory=lambda: UseCaseSettings(
            name="default",
            description="Default use case",
        ),
    )
    usecases: list[UseCaseSettings] = Field(default_factory=list)
    router: RouterSettings = Field(default_factory=RouterSettings)
    genai: GenAIProviderSettings = Field(
        description="Settings for GenAI integration, including model selection and configuration.",
        default_factory=lambda: GenAIOpenAISettings(),
        discriminator="sdk",
    )

    zammad: ZammadAPISettings | ZammadEAISettings = Field(
        description="Settings for Zammad integration, including API details and knowledge base configuration.",
        discriminator="type",
    )

    kafka: KafkaSettings = Field(
        description="Settings for Kafka integration, including broker URL, topic, and security configuration.",
        default_factory=lambda: KafkaSettings(),
    )

    polling: PollingSettings = Field(
        description="Settings for polling-based ticket intake, an alternative to Kafka for vanilla Zammad instances.",
        default_factory=lambda: PollingSettings(),
    )

    triage: TriageSettings = Field(
        description="Settings for triage step, including categories, actions, and rules.",
    )

    frontend: FrontendSettings = Field(
        description="Settings for optional mounted frontend, including auth and runtime behavior.",
        default_factory=lambda: FrontendSettings(),
    )

    answer: AnswerSettings = Field(
        description="Settings for answer generation step, including prompts and configuration.",
        default_factory=lambda: AnswerSettings(),
    )

    log: LoggingSettings = Field(
        description="Settings for logging configuration, including format selection.",
        default_factory=lambda: LoggingSettings(),
    )

    max_user_text_length: PositiveInt = Field(
        description="Maximum combined length of article text and attachment content for triage/answer processing. Messages exceeding this length will be truncated to this limit.",
        default=2000,
    )

    recursion_limit: PositiveInt = Field(
        description="Maximum recursion depth limit for the agents to prevent the agent from running infinite tool call loops.",
        default=30,
    )

    api: APISettings = Field(
        description="Settings for the REST API, including authentication and rate limiting configuration.",
        default_factory=lambda: APISettings(),
    )

    langfuse_enabled: bool = Field(
        description="Whether to enable Langfuse integration for logging and prompt fetching.",
        default=True,
    )

    mode: Literal["production", "development", "unittest"] = Field(
        description="Application mode, affecting logging and other behavior.",
        default="production",
    )

    prometheus: PrometheusSettings = Field(
        description="Settings for Prometheus metrics exposure, including endpoint and port configuration.",
        default_factory=lambda: PrometheusSettings(),
    )

    guardrails: GuardrailSettings = Field(
        description="Settings for guardrail content safety evaluation.",
        default_factory=lambda: GuardrailSettings(),
    )
    preparser: "PreparserSettings" = Field(
        description="Settings for optional message preparsing before LLM processing.",
        default_factory=lambda: __import__(
            "app.settings.preparser", fromlist=["PreparserSettings"]
        ).PreparserSettings(),
    )

    @model_validator(mode="after")
    def set_log_defaults(self) -> "ZammadAISettings":
        """Set default logging format and level when they are not explicitly configured.

        If `log.format` or `log.level` is unset, populate them based on `mode`: use `"plain"` and `"DEBUG"` when mode is `"development"`, otherwise use `"json"` and `"INFO"`.

        Returns:
            ZammadAISettings: The settings instance with `log.format` and `log.level` set when they were previously `None`.
        """
        if self.log.format is None:
            self.log.format = "plain" if self.mode == "development" else "json"
        if self.log.level is None:
            self.log.level = "DEBUG" if self.mode == "development" else "INFO"
        return self

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
def get_settings() -> ZammadAISettings:
    """Provide the application's cached settings.

    Returns:
        ZammadAISettings: The cached settings instance used by the application.
    """
    settings = ZammadAISettings()
    if settings.usecases:
        _validate_usecases(settings.usecases, settings.router)
        return settings

    config_dir = Path(settings.router.usecase_config_dir)
    if not config_dir.is_absolute():
        config_dir = Path.cwd() / config_dir
    definitions = _load_usecase_definitions(config_dir)
    if definitions:
        settings.usecases = definitions
        _validate_usecases(definitions, settings.router)
    else:
        settings.usecases = [settings.usecase]
    return settings


def _load_usecase_definitions(config_dir: Path) -> list[UseCaseSettings]:
    """Load usecase definition files when the configured directory exists."""
    if _is_test_mode() or not config_dir.is_dir():
        return []

    definitions: list[UseCaseSettings] = []
    for path in sorted(config_dir.glob("*.yaml")):
        with path.open(encoding="utf-8") as file:
            payload: Any = yaml.safe_load(file) or {}
        if not isinstance(payload, dict):
            raise ValueError(f"Usecase configuration must be a mapping: {path}")
        definitions.append(UseCaseSettings.model_validate(payload))
    return definitions


def _validate_usecases(usecases: list[UseCaseSettings], router: RouterSettings | None = None) -> None:
    """Reject duplicate names and overlapping exact route definitions."""
    names = [usecase.name for usecase in usecases]
    if len(names) != len(set(names)):
        raise ValueError("Usecase names must be unique")

    if router is not None and router.unmatched_policy == "fallback":
        if router.fallback_usecase not in names:
            raise ValueError(f"Fallback usecase '{router.fallback_usecase}' is not configured")

    routes: list[tuple[str | None, str | None, str]] = []
    for usecase in usecases:
        for match in usecase.match:
            for request_type, action, previous_name in routes:
                if (match.request_type is None or request_type is None or match.request_type == request_type) and (
                    match.action is None or action is None or match.action == action
                ):
                    raise ValueError(
                        f"Kafka routes for '{usecase.name}' and '{previous_name}' overlap and are ambiguous"
                    )
            routes.append((match.request_type, match.action, usecase.name))

    polling_routes: list[tuple[int | None, str | None, str]] = []
    for usecase in usecases:
        for match in usecase.polling_match:
            for group_id, group_name, previous_name in polling_routes:
                if (match.group_id is None or group_id is None or match.group_id == group_id) and (
                    match.group_name is None or group_name is None or match.group_name == group_name
                ):
                    raise ValueError(
                        f"Polling routes for '{usecase.name}' and '{previous_name}' overlap and are ambiguous"
                    )
            polling_routes.append((match.group_id, match.group_name, usecase.name))
