from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, CliSettingsSource, PydanticBaseSettingsSource, SettingsConfigDict, YamlConfigSettingsSource

from .frontend import FrontendSettings
from .genai import GenAISettings
from .kafka import KafkaSettings
from .qdrant import QdrantSettings
from .triage import TriageSettings
from .usecase import UseCaseSettings
from .zammad import BaseZammadSettings


class ZammadAISettings(BaseSettings):
    """
    Application settings for Zammad AI integration.
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

    zammad: BaseZammadSettings = Field(
        description="Settings for Zammad integration, including API details and knowledge base configuration.",
    )

    qdrant: QdrantSettings = Field(
        description="Settings for Qdrant integration, including host, API key, and collection details.",
    )

    kafka: KafkaSettings = Field(
        description="Settings for Kafka integration, including broker URL, topic, and security configuration.",
        default_factory=lambda: KafkaSettings(),
    )

    triage: TriageSettings = Field(
        description="Settings for triage step, including categories, actions, and rules.",
    )

    frontend: FrontendSettings = Field(
        description="Settings for optional frontend.",
        default_factory=lambda: FrontendSettings(),
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

    model_config = SettingsConfigDict(
        env_prefix="ZAMMAD_AI_",
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        env_nested_delimiter="__",
        nested_model_default_partial_update=True,
        yaml_file="config.yaml",
        yaml_file_encoding="utf-8",
        cli_parse_args=True,
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
        """
        Define the precedence and ordering of configuration sources for the settings class.
        
        The returned tuple lists settings sources in precedence order (highest priority first): initialization values, CLI arguments, environment variables, dotenv (.env) file, and YAML configuration file.
        
        Returns:
            tuple[PydanticBaseSettingsSource, ...]: Settings sources in priority order.
        """
        return (
            init_settings,
            CliSettingsSource(settings_cls),
            env_settings,
            dotenv_settings,
            YamlConfigSettingsSource(settings_cls),
        )


@lru_cache(maxsize=1)
def get_settings() -> ZammadAISettings:
    """
    Provide the application's cached settings.
    
    Returns:
        ZammadAISettings: The cached settings instance used by the application.
    """

    return ZammadAISettings()  # type: ignore