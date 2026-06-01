"""Settings for Kafka connectivity and security."""

from typing import Literal

from pydantic import BaseModel, Field, FilePath


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


class EventProcessingSettings(BaseModel):
    """Settings related to processing of incoming events."""

    valid_request_types: list[str] = Field(
        default_factory=list,
        description="List of valid request types to process. Events with request types not in this list will be acknowledged and skipped. If empty, all request types are accepted.",
    )

    valid_action_types: list[str] = Field(
        default_factory=list,
        description="List of valid action types to process. Events with action types not in this list will be acknowledged and skipped. If empty, all action types are accepted.",
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
