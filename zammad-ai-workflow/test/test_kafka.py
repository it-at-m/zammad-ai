"""Tests for Kafka event routing and triage invocation."""

from collections.abc import Callable
from unittest.mock import AsyncMock, MagicMock

import pytest
from faststream.exceptions import AckMessage, NackMessage
from faststream.kafka import TestKafkaBroker

from app.errors import TriageCategoryWrongError, TriageError
from app.kafka.broker import build_router
from app.models.kafka import Event
from app.models.zammad import ZammadTicket, ZammadArticle
from app.models.triage import TriageResult
from app.settings import ZammadAISettings
from app.settings.answer import AnswerSettings, QdrantSettings
from app.settings.kafka import EventProcessingSettings, KafkaSettings
from app.settings.triage import (
    Action,
    ActionTypes,
    Category,
    StringTriagePrompts,
    TriageSettings,
)
from app.settings.zammad import ZammadAPISettings


def create_mock_settings() -> ZammadAISettings:
    """Builds a complete ZammadAISettings object populated with realistic test values for unit tests.

    Temporarily replaces sys.argv to avoid CLI argument parsing during construction.

    Returns:
        ZammadAISettings: Settings populated with zammad, qdrant, kafka, triage configuration, and valid_request_types suitable for tests.
    """
    import sys

    # Temporarily replace sys.argv to prevent CLI parsing
    original_argv = sys.argv
    try:
        sys.argv = ["zammad-ai"]  # Only the program name, no arguments
        return ZammadAISettings(
            mode="unittest",
            zammad=ZammadAPISettings(
                base_url="https://example.com",  # type: ignore
                auth_token="test-token",  # type: ignore
            ),
            answer=AnswerSettings(
                qdrant=QdrantSettings(
                    host="https://qdrant.example.com",  # type: ignore
                    api_key="test-key",  # type: ignore
                    collection_name="test_collection",
                ),
            ),
            kafka=KafkaSettings(
                broker_url="localhost:9092",
                group_id="test-group",
                topic="test-topic",
                event_processing=EventProcessingSettings(
                    valid_request_types=["technischer Bürgersupport"],
                    valid_action_types=["created", "updated"],
                ),
            ),
            triage=TriageSettings(
                categories=[Category(name="Test")],
                no_category_name="Test",
                actions=[Action(name="Keine_Aktion", description="No action", type=ActionTypes.NoAction)],
                no_action_name="Keine_Aktion",
                action_rules=[],
                prompts=StringTriagePrompts(),
            ),
            # keep compatibility: valid request types are set on kafka.event_processing
        )
    finally:
        sys.argv = original_argv


@pytest.fixture
def valid_message() -> dict:
    """Standard valid Kafka event payload used by tests.

    Returns:
        dict: Payload with keys:
            - action: event action (e.g., "created")
            - ticket: ticket identifier (e.g., "3720")
            - status: ticket status (e.g., "new")
            - statusId: status identifier (e.g., "1")
            - anliegenart: request type (e.g., "technischer Bürgersupport")
            - lhmExtId: external identifier (empty string when absent)
    """
    return {
        "action": "created",
        "ticket": "3720",
        "status": "new",
        "statusId": "1",
        "anliegenart": "technischer Bürgersupport",
        "lhmExtId": "",
    }


@pytest.fixture
def mock_triage() -> MagicMock:
    """Create a MagicMock that simulates a Triage with a preset async `perform_triage` result.

    Returns:
        MagicMock: A mock Triage object whose `perform_triage` is an AsyncMock returning a
        TriageResult with a Category(name="Test"), Action(name="Keine_Aktion", description="No action", type=ActionTypes.No_Action),
        reasoning "Test reasoning", and confidence 0.95.
    """
    triage = MagicMock()
    # Provide a zammad_client that returns a ticket when asked (router will call get_ticket)
    triage.zammad_client = MagicMock()
    triage.zammad_client.get_ticket = AsyncMock(
        return_value=ZammadTicket(id=3720, articles=[ZammadArticle(id=1, ticket_id=3720, text="msg")])
    )
    # Make perform_triage return an async mock that returns a TriageResult
    triage.perform_triage = AsyncMock(
        return_value=TriageResult(
            user_text="",
            category=Category(name="Test"),
            action=Action(name="Keine_Aktion", description="No action", type=ActionTypes.NoAction),
            reasoning="Test reasoning",
            confidence=0.95,
        )
    )
    return triage


@pytest.fixture
def mock_get_triage(monkeypatch: pytest.MonkeyPatch, mock_triage: MagicMock) -> None:
    """Patch Kafka router triage lookup to return a mocked triage object."""
    monkeypatch.setattr("app.kafka.broker.get_triage_service", lambda *args, **kwargs: mock_triage)


@pytest.fixture(autouse=True)
def mock_get_answer_service(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Patch Kafka router answer lookup to return a mocked answer service."""
    answer_service = MagicMock()
    answer_service.generate_answer = AsyncMock()
    monkeypatch.setattr("app.kafka.broker.get_answer_service", lambda *args, **kwargs: answer_service)
    return answer_service


@pytest.fixture(autouse=True)
def mock_get_action_service(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Patch Kafka router action lookup to return a mocked action service."""
    action_service = MagicMock()
    action_service.execute_action = AsyncMock()
    monkeypatch.setattr("app.kafka.broker.get_action_service", lambda *args, **kwargs: action_service)
    return action_service


@pytest.mark.asyncio
async def test_event_handler_valid_message(
    kafka_message_factory: Callable[..., dict[str, str]],
    mock_triage: MagicMock,
    mock_get_triage: None,
    settings_factory: Callable[..., ZammadAISettings],
) -> None:
    """Verifies that a valid Kafka message causes the triage service to be invoked with the ticket ID from the message.

    Publishes a message to the router's broker configured with a single allowed request type and asserts that `perform_triage` is called once with `id=3720`.
    """
    settings = settings_factory(valid_request_types=["technischer Bürgersupport"])
    router, _ = build_router(settings=settings)
    async with TestKafkaBroker(router.broker) as test_broker:
        message = kafka_message_factory()
        await test_broker.publish(topic=settings.kafka.topic, message=message)
        # Verify the triage was called with the correct ticket ID
        assert mock_triage.perform_triage.call_count == 1
        called_ticket = mock_triage.perform_triage.call_args.kwargs.get("ticket")
        assert called_ticket is not None and called_ticket.id == 3720


@pytest.mark.asyncio
async def test_event_handler_with_requestType_alias(
    kafka_message_factory: Callable[..., dict[str, str]],
    mock_triage: MagicMock,
    mock_get_triage: None,
    settings_factory: Callable[..., ZammadAISettings],
) -> None:
    """Test event handler accepts requestType as alias for anliegenart."""
    settings = settings_factory(valid_request_types=["technischer Bürgersupport"])
    router, _ = build_router(settings=settings)
    async with TestKafkaBroker(router.broker) as test_broker:
        message = kafka_message_factory()
        # Use alias instead of anliegenart
        message.pop("anliegenart", None)
        message["requestType"] = "technischer Bürgersupport"
        await test_broker.publish(topic=settings.kafka.topic, message=message)
        # Verify the triage was called with the correct ticket ID
        assert mock_triage.perform_triage.call_count == 1
        called_ticket = mock_triage.perform_triage.call_args.kwargs.get("ticket")
        assert called_ticket is not None and called_ticket.id == 3720


@pytest.mark.asyncio
async def test_event_handler_invalid_request_type(
    kafka_message_factory: Callable[..., dict[str, str]],
    mock_triage: MagicMock,
    mock_get_triage: None,
    settings_factory: Callable[..., ZammadAISettings],
    caplog,
) -> None:
    """Verify that messages whose request type is not listed in the configured valid_request_types are skipped by the event handler.

    When a message contains an invalid request type, the handler logs an informational "Skipping" message and does not invoke the triage service.
    """
    settings = settings_factory(valid_request_types=["technischer Bürgersupport"])
    router, _ = build_router(settings=settings)
    async with TestKafkaBroker(router.broker) as test_broker:
        message = kafka_message_factory(anliegenart="invalid_request_type")
        message["anliegenart"] = "invalid_request_type"
        with caplog.at_level("INFO"):
            await test_broker.publish(topic=settings.kafka.topic, message=message)
        assert "Skipping" in caplog.text
        # Verify triage was NOT called for invalid request types
        mock_triage.perform_triage.assert_not_called()


@pytest.mark.asyncio
async def test_event_handler_invalid_message_format(
    mock_triage: MagicMock,
    mock_get_triage: None,
    settings_factory: Callable[..., ZammadAISettings],
) -> None:
    """Malformed payloads should be treated as permanent payload errors and dropped."""
    settings = settings_factory(valid_request_types=["technischer Bürgersupport"])
    router, _ = build_router(settings=settings)
    async with TestKafkaBroker(router.broker) as test_broker:
        # Missing required fields
        invalid_message: dict = {
            "action": "created",
            # Missing required fields: ticket, status, statusId, request_type
        }
        await test_broker.publish(topic=settings.kafka.topic, message=invalid_message)

    mock_triage.perform_triage.assert_not_called()


@pytest.mark.asyncio
async def test_event_handler_with_multiple_valid_request_types(
    kafka_message_factory: Callable[..., dict[str, str]],
    mock_triage: MagicMock,
    mock_get_triage: None,
    settings_factory: Callable[..., ZammadAISettings],
) -> None:
    """Verify the event handler invokes triage when the message's request type matches any of multiple allowed types.

    Publishes a Kafka message with `anliegenart` set to "general support" while the settings allow ["technischer Bürgersupport", "general support", "other"], and asserts `perform_triage` was called with `id=3720`.
    """
    settings = settings_factory(valid_request_types=["technischer Bürgersupport", "general support", "other"])
    router, _ = build_router(settings=settings)
    async with TestKafkaBroker(router.broker) as test_broker:
        message = kafka_message_factory(anliegenart="general support")
        await test_broker.publish(topic=settings.kafka.topic, message=message)
        # Verify the triage was called with the correct ticket ID
        assert mock_triage.perform_triage.call_count == 1
        called_ticket = mock_triage.perform_triage.call_args.kwargs.get("ticket")
        assert called_ticket is not None and called_ticket.id == 3720


@pytest.mark.asyncio
async def test_event_handler_case_sensitive_request_type(
    kafka_message_factory: Callable[..., dict[str, str]],
    mock_triage: MagicMock,
    mock_get_triage: None,
    settings_factory: Callable[..., ZammadAISettings],
    caplog,
) -> None:
    """Test that request type validation is case sensitive."""
    settings = settings_factory(valid_request_types=["technischer Bürgersupport"])
    router, event_handler = build_router(settings=settings)
    async with TestKafkaBroker(router.broker) as test_broker:
        message = kafka_message_factory(anliegenart="TECHNISCHER BÜRGERSUPPORT")
        with caplog.at_level("INFO"):
            await test_broker.publish(topic=settings.kafka.topic, message=message)
        assert "Skipping event" in caplog.text
        # Verify triage was NOT called for case mismatch
        mock_triage.perform_triage.assert_not_called()


@pytest.mark.asyncio
async def test_event_handler_nack_on_retryable_typed_error(
    kafka_message_factory: Callable[..., dict[str, str]],
    mock_triage: MagicMock,
    mock_get_triage: None,
    settings_factory: Callable[..., ZammadAISettings],
) -> None:
    """Retryable typed triage errors must produce NACK to trigger broker retry."""
    settings = settings_factory(valid_request_types=["technischer Bürgersupport"])
    router, event_handler = build_router(settings=settings)
    mock_triage.perform_triage.side_effect = TriageError("retryable triage", retryable=True)

    event = Event.model_validate(kafka_message_factory())
    with pytest.raises(NackMessage):
        await event_handler(event=event)


@pytest.mark.asyncio
async def test_event_handler_ack_on_permanent_typed_error(
    kafka_message_factory: Callable[..., dict[str, str]],
    mock_triage: MagicMock,
    mock_get_triage: None,
    settings_factory: Callable[..., ZammadAISettings],
) -> None:
    """Permanent typed triage errors must be dropped with ACK."""
    settings = settings_factory(valid_request_types=["technischer Bürgersupport"])
    router, event_handler = build_router(settings=settings)
    mock_triage.perform_triage.side_effect = TriageError("permanent triage", retryable=False)

    event = Event.model_validate(kafka_message_factory())
    with pytest.raises(AckMessage):
        await event_handler(event=event)


@pytest.mark.asyncio
async def test_event_handler_ack_on_invalid_ticket_id(
    kafka_message_factory: Callable[..., dict[str, str]],
    mock_triage: MagicMock,
    mock_get_triage: None,
    settings_factory: Callable[..., ZammadAISettings],
) -> None:
    """Non-numeric ticket ids are treated as payload errors and dropped."""
    settings = settings_factory(valid_request_types=["technischer Bürgersupport"])
    router, event_handler = build_router(settings=settings)

    event = Event.model_validate(kafka_message_factory(ticket="bad-ticket-id"))
    with pytest.raises(AckMessage):
        await event_handler(event=event)

    mock_triage.perform_triage.assert_not_called()


@pytest.mark.asyncio
async def test_event_handler_category_wrong_retries_below_threshold(
    kafka_message_factory: Callable[..., dict[str, str]],
    mock_triage: MagicMock,
    mock_get_triage: None,
    settings_factory: Callable[..., ZammadAISettings],
) -> None:
    """Category wrong errors with low confidence are retried."""
    settings = settings_factory(valid_request_types=["technischer Bürgersupport"])
    settings.triage.category_wrong_retry_confidence_threshold = 0.7
    router, event_handler = build_router(settings=settings)
    mock_triage.perform_triage.side_effect = TriageCategoryWrongError(
        "category mismatch",
        confidence=0.2,
    )

    event = Event.model_validate(kafka_message_factory())
    with pytest.raises(NackMessage):
        await event_handler(event=event)


@pytest.mark.asyncio
async def test_event_handler_category_wrong_drops_above_threshold(
    kafka_message_factory: Callable[..., dict[str, str]],
    mock_triage: MagicMock,
    mock_get_triage: None,
    settings_factory: Callable[..., ZammadAISettings],
) -> None:
    """Category wrong errors with high confidence are dropped."""
    settings = settings_factory(valid_request_types=["technischer Bürgersupport"])
    settings.triage.category_wrong_retry_confidence_threshold = 0.7
    router, event_handler = build_router(settings=settings)
    mock_triage.perform_triage.side_effect = TriageCategoryWrongError(
        "category mismatch",
        confidence=0.9,
    )

    event = Event.model_validate(kafka_message_factory())
    with pytest.raises(AckMessage):
        await event_handler(event=event)


@pytest.mark.asyncio
async def test_event_handler_executes_action_when_triage_returns_action(
    kafka_message_factory: Callable[..., dict[str, str]],
    mock_triage: MagicMock,
    mock_get_triage: None,
    settings_factory: Callable[..., ZammadAISettings],
    mock_get_action_service: MagicMock,
) -> None:
    """Verify that when triage returns a result, the action service is invoked."""
    settings = settings_factory(valid_request_types=["technischer Bürgersupport"])
    router, _ = build_router(settings=settings)
    async with TestKafkaBroker(router.broker) as test_broker:
        message = kafka_message_factory()
        await test_broker.publish(topic=settings.kafka.topic, message=message)
        mock_get_action_service.execute_action.assert_called_once()
