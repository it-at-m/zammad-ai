"""Security helpers for configuring Kafka TLS/mTLS."""

import binascii
from base64 import b64decode
from pathlib import Path
from ssl import SSLContext, create_default_context
from tempfile import TemporaryDirectory

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization import pkcs12
from faststream.security import BaseSecurity

from app.core.settings.kafka import KafkaMTLSEnvSecurity, KafkaMTLSFileSecurity, KafkaSettings
from app.utils.logging import getLogger

logger = getLogger(__name__)


def setup_security(kafka_settings: KafkaSettings) -> BaseSecurity:
    """
    Configure and return a BaseSecurity for Kafka based on the provided KafkaSettings.
    
    Returns:
        BaseSecurity: A security object configured with an SSLContext and use_ssl=True when mTLS is configured; returns a default (no-security) BaseSecurity if kafka_settings.security is None.
    
    Raises:
        ValueError: If environment-provided base64 fields are invalid, if the PKCS#12 data or password cannot be decoded or loaded, if the PKCS#12 archive lacks a private key or certificate, or if the kafka_settings.security type is unsupported.
    """
    if kafka_settings.security is None:
        logger.debug("No Kafka security configuration provided; using no security.")
        return BaseSecurity()

    with TemporaryDirectory() as tempdir:
        tempdir_path: Path = Path(tempdir)
        if isinstance(kafka_settings.security, KafkaMTLSEnvSecurity):
            logger.debug("Setting up Kafka mTLS security using environment variables.")
            # Unpack CA file
            try:
                ca_data = b64decode(s=kafka_settings.security.ca_file_base64).decode(encoding="utf-8")
            except binascii.Error as e:  # Malformed base64 raises binascii.Error
                raise ValueError(f"Setting 'settings.kafka.security.ca_file_base64' contains invalid base64 data: {e}") from e

            # Unpack PKCS#12 file
            try:
                pkcs12_bytes = b64decode(s=kafka_settings.security.pkcs12_base64)
            except binascii.Error as e:
                raise ValueError(f"Setting 'settings.kafka.security.pkcs12_base64' contains invalid base64 data: {e}") from e

            # Unpack PKCS#12 password
            try:
                pkcs12_pw_bytes: bytes = b64decode(s=kafka_settings.security.pkcs12_pw_base64)
            except binascii.Error as e:
                raise ValueError(f"Setting 'settings.kafka.security.pkcs12_pw_base64' contains invalid base64 data: {e}") from e

            # Extract the private key and certificate from the PKCS#12 file
            try:
                private_key, certificate, _ = pkcs12.load_key_and_certificates(
                    data=pkcs12_bytes,
                    password=pkcs12_pw_bytes,
                )
            except Exception as e:
                raise ValueError(f"Failed to load PKCS#12 file: {e}")

            if private_key is None or certificate is None:
                raise ValueError("PKCS#12 file does not contain a private key and certificate.")

            # Write cert and key to temporary files
            cert_file: Path = tempdir_path / "kafka.cert"
            key_file: Path = tempdir_path / "kafka.key"
            with open(file=cert_file, mode="wb") as f:
                f.write(certificate.public_bytes(encoding=serialization.Encoding.PEM))
            with open(file=key_file, mode="wb") as f:
                f.write(
                    private_key.private_bytes(
                        encoding=serialization.Encoding.PEM,
                        format=serialization.PrivateFormat.TraditionalOpenSSL,
                        encryption_algorithm=serialization.NoEncryption(),
                    )
                )
        elif isinstance(kafka_settings.security, KafkaMTLSFileSecurity):
            # Load CA data from file
            with open(file=kafka_settings.security.ca_file_path, mode="r") as f:
                ca_data = f.read()

            # Use provided cert and key files
            cert_file: Path = kafka_settings.security.client_cert_path
            key_file: Path = kafka_settings.security.client_key_path
        else:
            raise ValueError("Unsupported Kafka security configuration.")

        # Create SSL context
        ssl_context: SSLContext = create_default_context(
            cadata=ca_data,
        )

        # Load client cert and key
        ssl_context.load_cert_chain(
            certfile=cert_file,
            keyfile=key_file,
        )

    return BaseSecurity(ssl_context=ssl_context, use_ssl=True)