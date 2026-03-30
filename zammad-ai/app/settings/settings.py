"""Application settings and configuration source loading."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import (
    BaseSettings,
    CliSettingsSource,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

from .answer import AnswerSettings
from .frontend import FrontendSettings
from .genai import GenAISettings
from .kafka import KafkaSettings
from .logging import LoggingSettings
from .prometheus import PrometheusSettings
from .triage import TriageSettings
from .usecase import UseCaseSettings
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
    genai: GenAISettings = Field(
        description="Settings for GenAI integration, including model selection and configuration.",
        default_factory=lambda: GenAISettings(),
    )

    zammad: ZammadAPISettings | ZammadEAISettings = Field(
        description="Settings for Zammad integration, including API details and knowledge base configuration.",
        discriminator="type",
    )

    kafka: KafkaSettings = Field(
        description="Settings for Kafka integration, including broker URL, topic, and security configuration.",
        default_factory=lambda: KafkaSettings(),
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

    valid_request_types: list[str] = Field(
        min_length=1,
        description="List of valid request types to be processed",
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
    return ZammadAISettings()  # type: ignore
