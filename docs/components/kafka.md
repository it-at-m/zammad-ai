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

The service does not automatically process every event received from Kafka. The
`match` rules of the configured usecases decide which events are processed. A
usecase without `match` rules never matches an event, whether it is the only
configured usecase or one of many. Events that match no usecase follow
`router.unmatched_policy`: with the default `skip` policy the event is
acknowledged and dropped with an INFO log entry, with `error` it is also
acknowledged and dropped but with an ERROR log entry (the event is not
redelivered, so a usecase configuration gap cannot cause an infinite
redelivery loop), and with `fallback` it is routed to the usecase named by
`router.fallback_usecase`. Both `skip` and `error` record a
`skipped_unmatched_usecase` outcome in `zammad_ai_kafka_ticket_outcomes_total`.

Match rules must be unique per ticket: configure them so that every ticket
matches at most one usecase. Deliveries for the same ticket are not serialized
— the service processes events concurrently (`kafka.max_workers`) and can run
in multiple replicas — so overlapping rules could let two usecases process the
same ticket at the same time.

## Kafka Configuration & Security

Kafka settings are nested under the `kafka` key in `config.yaml` and support environment variable overrides using the prefix `ZAMMAD_AI_KAFKA__`. Security settings are further nested under `security`.

### Example YAML

```yaml
kafka:
  broker_url: "localhost:9092"
  topic: "ticket-events"
  retry_topic: "ticket-events-retry"
  group_id: "zammad-ai"

  retry_delay_seconds: 300
  max_retry_attempts: 3

  # Retries for moving a ticket back to its original group after processing.
  # Waits group_restore_retry_delay_seconds (doubled per attempt) between attempts.
  # Keep the total wait well below max_poll_interval_ms.
  group_restore_retry_attempts: 2
  group_restore_retry_delay_seconds: 5.0

  max_workers: 5 # Maximum number of concurrent workers for processing events

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
- `ZAMMAD_AI_KAFKA__RETRY_TOPIC`
- `ZAMMAD_AI_KAFKA__RETRY_DELAY_SECONDS`
- `ZAMMAD_AI_KAFKA__MAX_RETRY_ATTEMPTS`
- `ZAMMAD_AI_KAFKA__GROUP_RESTORE_RETRY_ATTEMPTS`
- `ZAMMAD_AI_KAFKA__GROUP_RESTORE_RETRY_DELAY_SECONDS`
- `ZAMMAD_AI_KAFKA__SECURITY__CA_FILE_BASE64`
- `ZAMMAD_AI_KAFKA__SECURITY__PKCS12_BASE64`
- `ZAMMAD_AI_KAFKA__SECURITY__PKCS12_PW`

Event filtering is not configured via Kafka environment variables. Which events
are processed is decided by the usecase `match` rules together with
`router.unmatched_policy` — see [Event Filtering](#event-filtering).

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

## Retry Flow

- Retryable failures are republished to `kafka.retry_topic`.
- Retry messages carry `retry_after` and `retry_count` headers.
- `retry_after` uses exponential backoff based on `retry_delay_seconds`:
  - first retry: base delay
  - second retry: base delay times 2
  - third retry: base delay times 4
- Retrying stops after `kafka.max_retry_attempts` completed retries, at which point the event is acknowledged and dropped.
- Retries whose `usecase` header names a usecase that is no longer configured are acknowledged and dropped with a
  `dropped_unknown_usecase` outcome in `zammad_ai_kafka_ticket_outcomes_total` instead of being re-resolved from their
  payload, which could process them against a different Zammad instance than the one that produced the retry. The same
  outcome is recorded when a retry without a `usecase` header cannot be resolved from its payload (payload validation
  failure, or no matching usecase under the `error` policy); under the default `skip` policy such a retry instead
  records `skipped_unmatched_usecase`. Dropped retries are never redelivered.
- Moving a ticket back to its original group is retried in place before the event is handed to the retry topic:
  `kafka.group_restore_retry_attempts` additional attempts with `kafka.group_restore_retry_delay_seconds` base delay,
  doubled after each failed attempt (defaults: wait 5s, then 10s). This keeps transient Zammad connection errors from
  sending fully processed events to the retry topic. The restore is skipped when the ticket is no longer in the AI
  group — for example because an agent took over the ticket or an overlapping delivery for the same ticket already
  restored it — so a stale restore cannot move the ticket out of its current group.
