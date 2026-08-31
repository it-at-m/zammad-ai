# Prometheus Metrics

Zammad-AI exposes Prometheus metrics for the backend API, triage flow, answer generation, and Kafka processing.

## Metrics Endpoint

The application exports metrics on the standard Prometheus `/metrics` endpoint.

The metrics server is started during application startup when `prometheus.enabled` is true.

The default port is `9090`.

## Exported Metrics

### HTTP Metrics

Collected by the FastAPI middleware in the backend service:

- `zammad_ai_http_requests_total`
- `zammad_ai_http_request_duration_seconds`

These metrics are labeled by HTTP method, resolved route path, and status code.

### Triage Metrics

Collected while the triage service processes tickets:

- `zammad_ai_triage_run_duration_seconds`
- `zammad_ai_triage_runs_in_progress`

### Answer Metrics

Collected while the answer service generates responses:

- `zammad_ai_answer_run_duration_seconds`
- `zammad_ai_answer_runs_in_progress`

### Kafka Metrics

Kafka processing metrics use the `zammad_ai_kafka_*` prefix and are emitted by the Kafka middleware layer.

Business counters derived from Kafka processing are also exported:

- `zammad_ai_kafka_events_total`
  - Counts only main-topic Kafka events that pass payload parsing and request/action filtering.
  - Retry-topic events and filtered events are not counted.
- `zammad_ai_kafka_ticket_outcomes_total`
  - Counts Kafka-driven ticket outcomes with labels `category`, `action_type`, and `outcome`.
  - `action_type` values are normalized to `ai_answer`, `static_answer`, `no_action`, or `unknown`.
  - `outcome` values currently include `answer`, `shared_draft`, `manual`, and `aborted_with_error`.
  - When a ticket aborts before a triage result exists, `category="unknown"` and `action_type="unknown"` are used.

## Configuration

Prometheus is configured in `config.yaml` under the `prometheus` section:

```yaml
prometheus:
  enabled: true
  port: 9090
```

Environment variables use the `ZAMMAD_AI_PROMETHEUS__` prefix.

## Local Development

The local compose stack includes a Prometheus container and a Grafana container.

- Prometheus scrapes `host.docker.internal:9090` every 15 seconds.
- Grafana is available on port `3000`.
- Prometheus persistence is stored in the `prometheus_data` volume.
