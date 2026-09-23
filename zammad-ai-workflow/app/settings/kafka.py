"""Settings for Kafka connectivity and security."""

from typing import Any, Literal

from pydantic import BaseModel, Field, FilePath, NonNegativeInt, PositiveInt, model_validator


class KafkaSettings(BaseModel):
    """Settings related to Kafka integration."""

    silent_fallback: bool = Field(
        description="Whether to silently fallback to REST only mode if Kafka is unreachable at startup. If false, the application will fail to start if Kafka is not reachable.",
        default=False,
    )

    broker_url: str = Field(
        description="URL of the Kafka message broker notifying ticket events.",
        default="localhost:9092",
    )

    topic: str = Field(
        description="Kafka topic for ticket events",
        default="ticket-events",
    )

    retry_topic: str = Field(
        description="Kafka topic for retryable ticket events",
        default="ticket-events-retry",
    )

    retry_delay_seconds: NonNegativeInt = Field(
        description="Base delay before retrying a failed event.",
        default=300,
    )

    max_retry_attempts: NonNegativeInt = Field(
        description="Maximum number of retry attempts after the initial processing attempt.",
        default=3,
    )

    client_id: str = Field(
        description="Kafka client ID used for the consumer name.",
        default="zammad-ai",
    )

    group_id: str | None = Field(
        description="Kafka consumer group ID",
        default=None,
    )

    security: "MTLSKafkaEnvSecurity | MTLSFileKafkaSecurity | DisableKafkaSecurity" = Field(
        description="Security configuration for Kafka connection.",
        default_factory=lambda: DisableKafkaSecurity(),
        discriminator="type",
    )
    event_processing: "EventProcessingSettings" = Field(
        description="Settings related to processing of incoming events.",
        default_factory=lambda: EventProcessingSettings(),
    )
    max_workers: PositiveInt = Field(
        description="Maximum number of concurrent workers for processing events.",
        default=5,
    )

    max_poll_interval_ms: PositiveInt = Field(
        description="Maximum time between Kafka poll calls before the consumer is considered dead.",
        default=300_000,
    )

    @model_validator(mode="before")
    @classmethod
    def infer_security_type(cls, data: Any) -> Any:
        """Infer the Kafka security discriminator when config sources omit it.

        Environment and YAML sources can materialize the nested security payload without the
        explicit ``type`` field required by the discriminated union. Normalize those inputs
        before model validation so the configured security backend can still be parsed.
        """
        if not isinstance(data, dict):
            return data

        security = data.get("security")
        if not isinstance(security, dict) or "type" in security:
            return data

        normalized_security = dict(security)
        if {"ca_file_path", "client_cert_path", "client_key_path"} & normalized_security.keys():
            normalized_security["type"] = "file"
        elif {"ca_file_base64", "pkcs12_base64", "pkcs12_pw"} & normalized_security.keys():
            normalized_security["type"] = "env"
        else:
            return data

        normalized_data = dict(data)
        normalized_data["security"] = normalized_security
        return normalized_data


class EventProcessingSettings(BaseModel):
    """Settings related to processing of incoming events."""

    valid_request_types: list[str] = Field(
        default_factory=list,
        description="List of valid request types to process. Events with request types not in this list will be acknowledged and skipped.",
    )

    valid_action_types: list[str] = Field(
        default_factory=list,
        description="List of valid action types to process. Events with action types not in this list will be acknowledged and skipped.",
    )


class DisableKafkaSecurity(BaseModel):
    """Explicitly disable Kafka security (e.g., for plaintext connections)."""

    type: Literal["none"] = "none"


class MTLSKafkaEnvSecurity(BaseModel):
    """mTLS configuration for Kafka connection using environment variables only."""

    type: Literal["env"] = "env"

    ca_file_base64: str = Field(
        description="Base64-encoded CA certificate.",
    )

    pkcs12_base64: str = Field(
        description="Base64-encoded PKCS#12 payload.",
    )

    pkcs12_pw: str = Field(
        description="PKCS#12 password in cleartext.",
    )


class MTLSFileKafkaSecurity(BaseModel):
    """mTLS configuration for Kafka connection using file paths."""

    type: Literal["file"] = "file"

    ca_file_path: FilePath = Field(
        description="Path to the CA certificate file (PEM format).",
    )

    client_cert_path: FilePath = Field(
        description="Path to the client certificate file (PEM format).",
    )

    client_key_path: FilePath = Field(
        description="Path to the client private key file (PEM format).",
    )


KafkaSettings.model_rebuild()
