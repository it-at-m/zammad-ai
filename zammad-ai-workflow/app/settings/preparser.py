"""Preparser settings and discriminated config types."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator


class BasePreparserConfig(BaseModel):
    """Base config for Preparsers."""

    type: str


class TablePreparserConfig(BasePreparserConfig):
    """Config for TablePreparser."""

    type: Literal["table"] = Field("table", description="Table preparser type")
    row_titles: list[str]
    case_sensitive: bool = Field(False, description="If true, match row titles case-sensitively")
    value_column: int = Field(1, description="Index of column to extract as the value (0-based)")


PreparserConfigTypes = Annotated[TablePreparserConfig, Field(discriminator="type")]


class PreparserSettings(BaseModel):
    """Settings for optional Preparser submodule."""

    enabled: bool = Field(False, description="Enable preparsing before LLM processing")
    config: PreparserConfigTypes | None = None

    @model_validator(mode="after")
    def _validate_config(self) -> "PreparserSettings":
        if self.enabled and self.config is None:
            raise ValueError("preparser.enabled is True but no preparser.config was provided")
        return self


# Ensure the central ZammadAISettings model is rebuilt now that PreparserSettings
# is defined so Pydantic's model linking (discriminators, nested models) is
# aware of the new type. Fail quietly if settings module is not importable at
# this time (tests/import-ordering will import it later and trigger rebuild).
try:
    from app.settings.settings import ZammadAISettings

    ZammadAISettings.model_rebuild()
except Exception:
    # Import errors here are non-fatal during module import ordering; the
    # settings module will call model_rebuild() when it's ready (or tests will
    # import in an order that triggers a rebuild).
    pass
