"""Usecase routing and configuration models."""

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class UseCaseMatch(BaseModel):
    """Exact Kafka event values that identify a usecase."""

    request_type: str | None = None
    action: str | None = None

    @model_validator(mode="after")
    def validate_not_empty(self) -> "UseCaseMatch":
        """Require at least one event field in the route."""
        if self.request_type is None and self.action is None:
            raise ValueError("A usecase match must define request_type or action")
        return self


class PollingMatch(BaseModel):
    """Ticket fields used to route polling intake."""

    group_id: int | None = None
    group_name: str | None = None

    @model_validator(mode="after")
    def validate_not_empty(self) -> "PollingMatch":
        """Require at least one ticket field in the route."""
        if self.group_id is None and self.group_name is None:
            raise ValueError("A polling match must define group_id or group_name")
        return self


class UseCaseSettings(BaseModel):
    """Definition of one configured usecase."""

    name: str = "default"
    description: str = "Default use case"
    match: list[UseCaseMatch] = Field(default_factory=list)
    polling_match: list[PollingMatch] = Field(default_factory=list)
    config: dict[str, Any] = Field(default_factory=dict)


class RouterSettings(BaseModel):
    """Shared settings for usecase discovery and unmatched events."""

    usecase_config_dir: str = "config/usecases"
    unmatched_policy: Literal["skip", "fallback", "error"] = "skip"
    fallback_usecase: str | None = None

    @model_validator(mode="after")
    def validate_fallback(self) -> "RouterSettings":
        """Require a fallback target when unmatched events use that policy."""
        if self.unmatched_policy == "fallback" and self.fallback_usecase is None:
            raise ValueError("fallback_usecase is required when unmatched_policy is 'fallback'")
        if self.unmatched_policy != "fallback" and self.fallback_usecase is not None:
            raise ValueError("fallback_usecase is only valid when unmatched_policy is 'fallback'")
        return self
