"""Prometheus business metrics shared across Kafka processing flows."""

from prometheus_client import Counter

from app.settings.triage import ActionTypes

KAFKA_EVENTS_TOTAL = Counter(
    name="zammad_ai_kafka_events_total",
    documentation="Total main-topic Kafka events that passed filtering and entered processing.",
)

KAFKA_TICKET_OUTCOMES_TOTAL = Counter(
    name="zammad_ai_kafka_ticket_outcomes_total",
    documentation="Total Kafka-driven ticket outcomes by triage category, action type, and outcome.",
    labelnames=("category", "action_type", "outcome"),
)


def record_processed_main_kafka_event() -> None:
    """Count a main-topic Kafka event once it passes filtering and enters processing."""
    KAFKA_EVENTS_TOTAL.inc()


def record_kafka_ticket_outcome(*, category: str | None, action_type: ActionTypes | str | None, outcome: str) -> None:
    """Count a Kafka-driven ticket outcome with normalized labels."""
    KAFKA_TICKET_OUTCOMES_TOTAL.labels(
        category=(category or "unknown").strip() or "unknown",
        action_type=_normalize_action_type(action_type),
        outcome=outcome,
    ).inc()


def _normalize_action_type(action_type: ActionTypes | str | None) -> str:
    """Normalize configured action types to stable Prometheus label values."""
    if action_type == ActionTypes.AIAnswer or action_type == "AIAnswer":
        return "ai_answer"
    if action_type == ActionTypes.StaticAnswer or action_type == "StaticAnswer":
        return "static_answer"
    if action_type == ActionTypes.NoAction or action_type == "NoAction":
        return "no_action"
    if isinstance(action_type, str) and action_type.strip():
        return action_type.strip().lower()
    return "unknown"
