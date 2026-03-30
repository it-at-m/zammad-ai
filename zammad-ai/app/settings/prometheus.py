"""Prometheus-related application settings."""

from pydantic import BaseModel, Field, field_validator


class PrometheusSettings(BaseModel):
    """Settings for Prometheus configuration."""

    enabled: bool = Field(
        description="Whether to enable Prometheus metrics endpoint. Defaults to True.",
        default=True,
    )
    port: int = Field(
        description="Port to expose Prometheus metrics on. Defaults to 19190.",
        default=9090,
        ge=1,
        le=65535,
    )

    @field_validator("port")
    def validate_port(cls, value: int) -> int:
        """Ensure the metrics port does not conflict with the main app port."""
        if value == 8080:
            raise ValueError("Prometheus metrics cannot be exposed on the same port as the main application (8080).")
        return value
