from typing import Generator
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.exceptions import RequestValidationError
from faststream.kafka import TestKafkaBroker

from app.core import context
from app.core.context import BackendContext
from app.core.settings import ZammadAISettings
from app.core.settings.kafka import KafkaSettings
from app.core.settings.qdrant import QdrantSettings
from app.core.settings.triage import (
    Action,
    Category,
    StringTriagePrompts,
    TriageSettings,
)
from app.core.settings.zammad import ZammadAPISettings
from app.kafka.broker import build_router
from app.models.triage import TriageResult


def create_mock_settings() -> ZammadAISettings:
    """
    Builds a complete ZammadAISettings object populated with realistic test values for unit tests.
    
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
            qdrant=QdrantSettings(
                host="https://qdrant.example.com",  # type: ignore
                api_key="test-key",  # type: ignore
                collection_name="test_collection",
            ),
            kafka=KafkaSettings(
                broker_url="localhost:9092",
                group_id="test-group",
                topic="test-topic",
            ),
            triage=TriageSettings(
                categories=[Category(name="Test", id=1)],
                no_category_id=1,
                actions=[Action(name="Test", description="Test", id=1)],
                no_action_id=1,
                action_rules=[],
                prompts=StringTriagePrompts(),
            ),
            valid_request_types=["technischer Bürgersupport"],
        )
    finally:
        sys.argv = original_argv


@pytest.fixture
def valid_message() -> dict:
    """
    Standard valid Kafka event payload used by tests.
    
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
    """
    Create a MagicMock that simulates a Triage with a preset async `perform_triage` result.
    
    Returns:
        MagicMock: A mock Triage object whose `perform_triage` is an AsyncMock returning a
        TriageResult with a Category(name="Test", id=1), Action(name="Test", description="Test", id=1),
        reasoning "Test reasoning", and confidence 0.95.
    """
    triage = MagicMock()
    # Make perform_triage return an async mock that returns a TriageResult
    triage.perform_triage = AsyncMock(
        return_value=TriageResult(
            category=Category(name="Test", id=1),
            action=Action(name="Test", description="Test", id=1),
            reasoning="Test reasoning",
            confidence=0.95,
        )
    )
    return triage


@pytest.fixture
def mock_backend_context(mock_triage) -> Generator[BackendContext, None, None]:
    """
    Create and inject a mocked BackendContext into the module for use in tests.
    
    Parameters:
        mock_triage (MagicMock): A mock triage object to attach to the backend context; its
            `perform_triage` coroutine will be called by code under test.
    
    Returns:
        Generator yielding the mocked BackendContext. The function sets `context.backend_context`
        to the created mock before yielding and resets `context.backend_context` to None after
        the generator finishes to restore global state.
    """
    settings = create_mock_settings()
    ctx = MagicMock(spec=BackendContext)
    ctx.triage = mock_triage
    ctx.settings = settings
    # Set the global backend_context variable
    context.backend_context = ctx
    yield ctx
    # Cleanup after test
    context.backend_context = None


@pytest.mark.asyncio
async def test_event_handler_valid_message(valid_message: dict, mock_backend_context) -> None:
    """Test event handler with a valid message."""
    settings = create_mock_settings()
    router, event_handler = build_router(settings=settings)
    async with TestKafkaBroker(router.broker) as test_broker:
        # copy fixture to avoid mutating the shared dict if a test modifies it
        message = dict(valid_message)
        await test_broker.publish(topic=settings.kafka.topic, message=message)
        # Verify the triage was called with the correct ticket ID
        mock_backend_context.triage.perform_triage.assert_called_once_with(id="3720")


@pytest.mark.asyncio
async def test_event_handler_with_requestType_alias(valid_message: dict, mock_backend_context) -> None:
    """Test event handler accepts requestType as alias for anliegenart."""
    settings = create_mock_settings()
    router, event_handler = build_router(settings=settings)
    async with TestKafkaBroker(router.broker) as test_broker:
        message = dict(valid_message)
        # Use alias instead of anliegenart
        message.pop("anliegenart", None)
        message["requestType"] = "technischer Bürgersupport"
        await test_broker.publish(topic=settings.kafka.topic, message=message)
        # Verify the triage was called with the correct ticket ID
        mock_backend_context.triage.perform_triage.assert_called_once_with(id="3720")


@pytest.mark.asyncio
async def test_event_handler_invalid_request_type(valid_message: dict, mock_backend_context, caplog) -> None:
    """Test event handler skips messages with invalid request types."""
    settings = create_mock_settings()
    router, event_handler = build_router(settings=settings)
    async with TestKafkaBroker(router.broker) as test_broker:
        message = dict(valid_message)
        message["anliegenart"] = "invalid_request_type"
        with caplog.at_level("INFO"):
            await test_broker.publish(topic=settings.kafka.topic, message=message)
        assert "Skipping" in caplog.text
        # Verify triage was NOT called for invalid request types
        mock_backend_context.triage.perform_triage.assert_not_called()


@pytest.mark.asyncio
async def test_event_handler_invalid_message_format(mock_backend_context) -> None:
    """Test event handler with malformed message that fails Pydantic validation."""
    settings = create_mock_settings()
    router, event_handler = build_router(settings=settings)
    async with TestKafkaBroker(router.broker) as test_broker:
        # Missing required fields
        invalid_message: dict = {
            "action": "created",
            # Missing required fields: ticket, status, statusId, request_type
        }
        with pytest.raises(expected_exception=RequestValidationError):
            await test_broker.publish(topic=settings.kafka.topic, message=invalid_message)


@pytest.mark.asyncio
async def test_event_handler_with_multiple_valid_request_types(valid_message: dict, mock_backend_context) -> None:
    """Test event handler with multiple valid request types configured."""
    settings = create_mock_settings()
    settings.valid_request_types = ["technischer Bürgersupport", "general support", "other"]
    router, event_handler = build_router(settings=settings)
    async with TestKafkaBroker(router.broker) as test_broker:
        message = dict(valid_message)
        message["anliegenart"] = "general support"
        await test_broker.publish(topic=settings.kafka.topic, message=message)
        # Verify the triage was called with the correct ticket ID
        mock_backend_context.triage.perform_triage.assert_called_once_with(id="3720")


@pytest.mark.asyncio
async def test_event_handler_case_sensitive_request_type(valid_message: dict, mock_backend_context, caplog) -> None:
    """Test that request type validation is case sensitive."""
    settings = create_mock_settings()
    settings.valid_request_types = ["technischer Bürgersupport"]  # exact case
    router, event_handler = build_router(settings=settings)
    async with TestKafkaBroker(router.broker) as test_broker:
        message = dict(valid_message)
        message["anliegenart"] = "TECHNISCHER BÜRGERSUPPORT"  # Different case
        with caplog.at_level("INFO"):
            await test_broker.publish(topic=settings.kafka.topic, message=message)
        assert "Skipping event" in caplog.text
        # Verify triage was NOT called for case mismatch
        mock_backend_context.triage.perform_triage.assert_not_called()