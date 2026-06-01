# Kafka / Message Broker

The system utilizes an Apache Kafka message broker to trigger its workflows.
The related Kafka topic is published by Zammad upon ticket creation or update events.
Our Zammad-AI service subscribes to this topic to process incoming tickets and generate AI-driven responses.

Events have the following structure:

```json
{
  "action": "created",
  "ticket": "3720",
  "status": "new",
  "statusId": "1",
  "anliegenart": "technischer Bürgersupport",
  "lhmExtId": ""
}
```

The structure is defined in the dbs/ticketing-eventing service and can be found in its [GitHub repository](https://github.com/it-at-m/dbs/blob/main/ticketing-eventing/handler-core/src/main/java/de/muenchen/oss/dbs/ticketing/eventing/handlercore/domain/model/Event.java).

## Event Filtering

The service does not automatically process every event received from Kafka. It uses the `kafka.event_processing.valid_request_types` configuration to filter events based on the `request_type` (or `anliegenart`) field.

- **Config Key**: `kafka.event_processing.valid_request_types` (list of strings)
- **Logic**: If the `request_type` of an incoming event is not in this list, the event is acknowledged and ignored. This prevents the service from responding to tickets it is not configured to handle.

## Kafka Configuration & Security

Kafka settings are nested under the `kafka` key in `config.yaml` and support environment variable overrides using the prefix `ZAMMAD_AI_KAFKA__`. Security settings are further nested under `security`.

### Example YAML

```yaml
kafka:
  broker_url: "localhost:9092"
  topic: "ticket-events"
  group_id: "zammad-ai"
  # event_processing holds filtering and processing-related options
  event_processing:
    valid_request_types:
      - "technischer Bürgersupport"
    valid_action_types:
      - "created"
      - "updated"

  # Security: choose one schema and set the discriminator `type` to `env` or `file`.
  security:
    type: env
    # For mTLS via environment variables (in-memory PKCS#12):
    ca_file_base64: "QkFTRTY0X0NBX0NFUlQ=" # base64-encoded CA cert
    pkcs12_base64: "QkFTRTY0X1BLQ1MxMl9CTE9C" # base64-encoded PKCS#12 blob
    pkcs12_pw: "cleartext-password" # PKCS#12 password in cleartext


  # Or, for file-based mTLS:
  # security:
  #   type: file
  #   ca_file_path: "/path/to/ca.pem"
  #   client_cert_path: "/path/to/client.crt"
  #   client_key_path: "/path/to/client.key"
```

### Environment Variable Overrides

Use double underscores for nesting. Important keys include:

- `ZAMMAD_AI_KAFKA__BROKER_URL`
- `ZAMMAD_AI_KAFKA__EVENT_PROCESSING__VALID_REQUEST_TYPES`
- `ZAMMAD_AI_KAFKA__EVENT_PROCESSING__VALID_ACTION_TYPES`
- `ZAMMAD_AI_KAFKA__SECURITY__CA_FILE_BASE64`
- `ZAMMAD_AI_KAFKA__SECURITY__PKCS12_BASE64`
- `ZAMMAD_AI_KAFKA__SECURITY__PKCS12_PW`

### Security Schemas

Kafka connections can be secured either via classic PEM files or via PKCS#12 blobs delivered through environment variables. Choose one of the following schemas:

#### Security schema: environment variables (`type: env`)

- `ca_file_base64`: Base64-encoded CA certificate
- `pkcs12_base64`: Base64-encoded PKCS#12 payload
- `pkcs12_pw`: PKCS#12 password in cleartext

#### Security schema: file paths (`type: file`)

- `ca_file_path`: Path to CA certificate file (PEM)
- `client_cert_path`: Path to client certificate file (PEM)
- `client_key_path`: Path to client private key file (PEM)

When using PKCS#12, the broker security layer decodes the secret in-memory, converts it to PEM, and feeds it into aiokafka's SSL context. The CA material is taken from the configured file or environment variable.
