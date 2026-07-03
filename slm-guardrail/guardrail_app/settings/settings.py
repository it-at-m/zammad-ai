"""Service settings for slm-guardrail (FastAPI)."""

from functools import lru_cache
from typing import Dict

from pydantic import BaseModel, Field
from pydantic_settings import (
    BaseSettings,
    CliSettingsSource,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)


class APISettings(BaseModel):
    """HTTP API server configuration."""

    host: str = Field(default="0.0.0.0", description="Bind host for FastAPI server")
    port: int = Field(default=8081, description="Bind port for FastAPI server", ge=1, le=65535)
    auth_token: str | None = Field(default=None, description="Optional bearer token for requests")
    max_payload_bytes: int = Field(default=65536, description="Max request payload size")


class GuardrailSettings(BaseModel):
    """Guardrail model behavior and storage settings."""

    confidence_threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    huggingface_cache_dir: str = Field(default="/app/huggingface_cache")
    offline_mode: bool = Field(default=True)
    # Maximum concurrent inferences allowed against the guardrail model
    max_concurrency: int = Field(default=4, ge=1, description="Max concurrent model inferences")
    # Default model id to use when client does not specify one
    default_model: str = Field(default="default", description="Default model id to use for evaluations")
    # Per-model configurations; key is model id
    models: Dict[str, "ModelConfig"] = Field(default_factory=dict)


class ModelConfig(BaseModel):
    """Configuration for a specific guardrail model instance."""

    hf_model_name: str = Field(default="fastino/gliguard-LLMGuardrails-300M", description="HuggingFace model name or local path")
    offline_mode: bool | None = Field(default=None, description="Override global offline_mode for this model")
    huggingface_cache_dir: str | None = Field(default=None, description="Override global HF cache dir for this model")
    max_concurrency: int | None = Field(default=None, ge=1, description="Max concurrent inferences for this model")


def _should_enable_cli() -> bool:
    """Return False when under test runners to avoid argparse conflicts."""
    import sys

    if "pytest" in sys.modules:
        return False
    argv_str = " ".join(sys.argv).lower()
    return not any(ind in argv_str for ind in ["pytest", "py.test", "unittest"])


class ServiceSettings(BaseSettings):
    """Top-level service settings with API and Guardrails configuration."""

    api: APISettings = Field(default_factory=APISettings)
    guardrails: GuardrailSettings = Field(default_factory=GuardrailSettings)

    model_config = SettingsConfigDict(
        env_prefix="SLM_GUARDRAIL_",
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        env_nested_delimiter="__",
        nested_model_default_partial_update=True,
        yaml_file="config.yaml",
        yaml_file_encoding="utf-8",
        cli_parse_args=_should_enable_cli(),
        cli_kebab_case=True,
        cli_prog_name="slm-guardrail",
        extra="ignore",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Define the precedence of settings sources (init, CLI, env, .env, YAML)."""
        sources = [
            init_settings,
            CliSettingsSource(settings_cls),
            env_settings,
            dotenv_settings,
            YamlConfigSettingsSource(settings_cls),
        ]
        return tuple(sources)


@lru_cache(maxsize=1)
def get_settings() -> ServiceSettings:
    """Return cached service settings instance."""
    s = ServiceSettings()
    # Ensure at least one default model is configured
    if not s.guardrails.models:
        s.guardrails.models = {"default": ModelConfig()}
        s.guardrails.default_model = "default"
    return s
