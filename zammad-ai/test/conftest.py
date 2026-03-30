"""Shared pytest fixtures for unit tests.

This module centralizes test setup for settings, logging, global state cleanup,
Kafka payloads, and reusable fake dependencies.
"""

import logging
import os
from collections.abc import Callable, Generator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from faststream.kafka import TestKafkaBroker
from pydantic import HttpUrl, SecretStr

from app.settings import (
    AnswerSettings,
    GenAISettings,
    KafkaSettings,
    TriageSettings,
    ZammadAISettings,
    ZammadAPISettings,
)
from app.settings.triage import Action, ActionRule, ActionTypes, Category, StringTriagePrompts
from test.fakes import FakeGenAIHandler, FakeLangfuseClient, FakeZammadClient

_TEST_ENV_DEFAULTS: dict[str, str] = {
    "ZAMMAD_AI_MODE": "unittest",
    "ZAMMAD_AI_DISABLE_YAML": "1",
    "ZAMMAD_AI_LANGFUSE_ENABLED": "false",
    "ZAMMAD_AI_ZAMMAD__TYPE": "api",
    "ZAMMAD_AI_ZAMMAD__BASE_URL": "https://example.com",
    "ZAMMAD_AI_ZAMMAD__AUTH_TOKEN": "test-token",
    "ZAMMAD_AI_TRIAGE": '{"categories":[{"name":"Unknown"}],"no_category_name":"Unknown","actions":[{"name":"No Action","description":"No action","type":"NoAction"}],"no_action_name":"No Action","action_rules":[],"prompts":{"type":"string","prompt_map":{"categories":"List of categories: {{categories}}","examples":"Examples: {{examples}}","role":"You are a helpful assistant that categorizes support requests into the above categories based on the content of the request."}}}',
    "ZAMMAD_AI_VALID_REQUEST_TYPES": '["support"]',
    "ZAMMAD_AI_QDRANT__API_KEY": "test-key",
}

DEFAULT_GENAI_PROMPTS = {
    "categories": "List of categories: {{categories}}",
    "examples": "Examples: {{examples}}",
    "role": "You are a helpful assistant that categorizes support requests into the above categories based on the content of the request.",
    "categorization": "Given the following support request, determine the most appropriate category from the provided list.",
    "days_since_request": "Given the following support request and the current date, determine how many days have passed since the request was made. ",
    "processing_id": "Given the following support request, determine a unique processing identifier that can be used to group related requests together.",
}


class _ApiTriageStub:
    def __init__(self) -> None:
        """Initialize the triage stub with default category and action placeholders.

        Attributes:
            no_category (Category): A fallback Category named "Unknown".
            no_action (Action): A fallback Action named "No Action".
        """
        self.no_category = Category(name="Unknown")
        self.no_action = Action(name="No Action", description="No action", type=ActionTypes.NoAction)

    async def predict_category(self, *_args, **_kwargs) -> Any:
        """Provide a stubbed CategorizationResult representing an "Unknown" category prediction.

        Returns:
            CategorizationResult: Result with `category` set to the module's `no_category` placeholder, `reasoning` equal to "stub", and `confidence` 1.0.
        """
        from app.models.triage import CategorizationResult

        return CategorizationResult(category=self.no_category, reasoning="stub", confidence=1.0)

    async def get_action_name(self, *_args, **_kwargs) -> str:
        """Get the default action name used by the triage stub.

        @returns
            Action name of the stub's default action as a `str`.
        """
        return self.no_action.name

    def _name_to_action(self, _action_name: str) -> Action:
        """Return the default stub Action regardless of the provided action name.

        Parameters:
            _action_name (str): Ignored action name.

        Returns:
            Action: The default Action instance used by the stub.
        """
        return self.no_action

    async def cleanup(self) -> None:
        """Perform any asynchronous cleanup required by the triage service.

        This stub implementation performs no actions.
        """
        return None


def pytest_configure() -> None:
    """Set deterministic environment defaults for all tests."""
    for key, value in _TEST_ENV_DEFAULTS.items():
        os.environ.setdefault(key, value)


@pytest.fixture(scope="session")
def base_settings() -> ZammadAISettings:
    """Provide one minimal valid settings object for reuse across tests."""
    return ZammadAISettings.model_construct(
        mode="unittest",
        langfuse_enabled=False,
        genai=GenAISettings(),
        zammad=ZammadAPISettings(
            base_url=HttpUrl(url="https://example.com"),
            auth_token=SecretStr(secret_value="test-token"),
        ),
        kafka=KafkaSettings(
            broker_url="localhost:9092",
            group_id="test-group",
            topic="test-topic",
        ),
        triage=TriageSettings.model_construct(
            categories=[Category(name="Unknown"), Category(name="General")],
            no_category_name="Unknown",
            actions=[
                Action(name="No Action", description="No action", type=ActionTypes.NoAction),
                Action(name="Escalate", description="Escalate", type=ActionTypes.StaticAnswer),
            ],
            no_action_name="No Action",
            action_rules=[],
            prompts=StringTriagePrompts(
                type="string",
                prompt_map={
                    "categories": DEFAULT_GENAI_PROMPTS["categories"],
                    "examples": DEFAULT_GENAI_PROMPTS["examples"],
                    "role": DEFAULT_GENAI_PROMPTS["role"],
                },
            ),
        ),
        answer=AnswerSettings(
            ai_answer_disclaimer="",
        ),
        valid_request_types=["support", "technischer Bürgersupport"],
    )


@pytest.fixture
def settings_factory(base_settings: ZammadAISettings) -> Callable[..., ZammadAISettings]:
    """Create a factory that produces modified copies of a ZammadAISettings instance for tests.

    The returned callable builds a deep copy of the provided base settings and applies optional overrides:
    - `action_rules`: replace the triage action rules.
    - `valid_request_types`: replace the list of valid request types.
    - arbitrary keyword overrides are applied via a deep update to the settings model.

    Parameters:
        base_settings (ZammadAISettings): Template settings used as the basis for produced instances.

    Returns:
        Callable[..., ZammadAISettings]: A factory callable that accepts `action_rules`, `valid_request_types`, and other keyword overrides and returns a new ZammadAISettings with those changes applied.
    """

    def _factory(
        *,
        action_rules: list[ActionRule] | None = None,
        valid_request_types: list[str] | None = None,
        **overrides: Any,
    ) -> ZammadAISettings:
        """Create a modified copy of the base ZammadAISettings with optional overrides.

        Parameters:
            action_rules (list[ActionRule] | None): If provided, replace the triage.action_rules list on the returned settings.
            valid_request_types (list[str] | None): If provided, set the settings.valid_request_types to this list.
            **overrides (Any): Arbitrary model field updates applied via a deep model copy; keys are setting attribute names.

        Returns:
            ZammadAISettings: A new settings instance derived from the base settings with the specified modifications applied.
        """
        settings = base_settings.model_copy(deep=True)
        if action_rules is not None:
            settings.triage.action_rules = action_rules
        if valid_request_types is not None:
            settings.valid_request_types = valid_request_types
        if overrides:
            settings = settings.model_copy(update=overrides, deep=True)
        return settings

    return _factory


@pytest.fixture(autouse=True)
def cleanup_settings_cache() -> Generator[None, None, None]:
    """Reset cached settings before and after each test."""
    from app.settings.settings import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def cleanup_log_config_cache() -> Generator[None, None, None]:
    """Reset cached logging configuration before and after each test."""
    from app.utils.logging import reset_logging_state

    reset_logging_state()
    yield
    reset_logging_state()


@pytest.fixture(autouse=True)
def cleanup_triage_singleton() -> Generator[None, None, None]:
    """Reset the shared triage singleton before and after each test to prevent state leakage.

    This fixture sets app.triage.triage._service to None before yielding and again after the test completes.
    """
    import app.triage.triage as triage_module

    triage_module._service = None
    yield
    triage_module._service = None


@pytest.fixture(autouse=True)
def mock_settings(
    monkeypatch: pytest.MonkeyPatch, settings_factory: Callable[..., ZammadAISettings]
) -> ZammadAISettings:
    """Patch the application's get_settings accessors to return a deterministic test settings instance.

    Parameters:
        settings_factory (Callable[..., ZammadAISettings]): Factory function that produces a ZammadAISettings instance for tests.

    Returns:
        ZammadAISettings: The created settings instance that will be returned by the patched get_settings calls.
    """
    settings = settings_factory()
    monkeypatch.setattr("app.settings.settings.get_settings", lambda: settings)
    monkeypatch.setattr("app.settings.get_settings", lambda: settings)
    return settings


@pytest.fixture
def mock_logger(monkeypatch: pytest.MonkeyPatch) -> logging.Logger:
    """Provide a preconfigured logger for tests and patch the application's logging factory to return it.

    Returns:
        logging.Logger: A logger named "zammad-ai.tests" with no handlers (uses a NullHandler) suitable for use in tests.
    """
    logger = logging.getLogger("zammad-ai.tests")
    logger.handlers.clear()
    logger.addHandler(logging.NullHandler())
    monkeypatch.setattr("app.utils.logging.getLogger", lambda _name="zammad-ai": logger)
    return logger


@pytest.fixture
def temp_logconf(tmp_path_factory: pytest.TempPathFactory) -> str:
    """Create a temporary YAML logging configuration file and return its filesystem path.

    Parameters:
        tmp_path_factory (pytest.TempPathFactory): pytest factory used to create a temporary directory for the file.

    Returns:
        str: Absolute path to the created `logconf.yaml` file.
    """
    path = tmp_path_factory.mktemp("logconf") / "logconf.yaml"
    path.write_text(
        """
version: 1
formatters:
  simple:
    format: '%(levelname)s %(name)s %(message)s'
handlers:
  console:
    class: logging.StreamHandler
    formatter: simple
    stream: ext://sys.stdout
loggers:
  zammad-ai:
    level: INFO
    handlers: [console]
    propagate: false
root:
  level: INFO
  handlers: [console]
""".strip(),
        encoding="utf-8",
    )
    return str(path)


@pytest.fixture
def kafka_message_factory() -> Callable[..., dict[str, str]]:
    """Return a factory that builds a valid Kafka payload dictionary, allowing optional string field overrides.

    The produced factory accepts keyword string arguments that override the default payload fields:
    `action`, `ticket`, `status`, `statusId`, `anliegenart`, and `lhmExtId`.

    Returns:
        Callable[..., dict[str, str]]: A callable that takes string keyword overrides and returns a payload dict with defaults applied and overrides merged in.
    """

    def _factory(**overrides: str) -> dict[str, str]:
        """Create a valid Kafka-style message payload and apply any provided field overrides.

        Parameters:
            **overrides (str): Keyword arguments where each key is a payload field name and each value
                replaces the default for that field in the returned payload.

        Returns:
            payload (dict[str, str]): A dictionary containing default message fields merged with any
            provided overrides.
        """
        payload = {
            "action": "created",
            "ticket": "3720",
            "status": "new",
            "statusId": "1",
            "anliegenart": "technischer Bürgersupport",
            "lhmExtId": "",
        }
        payload.update(overrides)
        return payload

    return _factory


@pytest.fixture
def valid_message(kafka_message_factory: Callable[..., dict[str, str]]) -> dict[str, str]:
    """Provides a backward-compatible valid Kafka message.

    Returns:
        dict: A dictionary representing a valid Kafka message payload.
    """
    return kafka_message_factory()


@pytest.fixture
def test_kafka_broker() -> Callable[[Any], TestKafkaBroker]:
    """Provide a factory that creates FastStream TestKafkaBroker instances for a router.

    Returns:
        factory (Callable[[Any], TestKafkaBroker]): A callable that accepts a router-like object and returns a TestKafkaBroker built from the router's `broker` attribute.
    """

    def _factory(router: Any) -> TestKafkaBroker:
        """Create a TestKafkaBroker bound to the provided router's broker.

        Parameters:
            router (Any): Router-like object exposing a `broker` attribute used to construct the TestKafkaBroker.

        Returns:
            TestKafkaBroker: A TestKafkaBroker instance connected to `router.broker`.
        """
        return TestKafkaBroker(router.broker)

    return _factory


@pytest.fixture
def fake_langfuse_client() -> FakeLangfuseClient:
    """Provide a FakeLangfuseClient configured for use in tests.

    Returns:
        FakeLangfuseClient: A fake Langfuse client instance suitable for test assertions and simulation.
    """
    return FakeLangfuseClient()


@pytest.fixture
def fake_genai_handler() -> FakeGenAIHandler:
    """Create a FakeGenAIHandler configured with default GenAISettings and prompts.

    Returns:
        handler (FakeGenAIHandler): A FakeGenAIHandler instance using a default GenAISettings() and DEFAULT_GENAI_PROMPTS.
    """
    return FakeGenAIHandler(
        genai_settings=GenAISettings(),
        prompts=DEFAULT_GENAI_PROMPTS,
    )


@pytest.fixture
def fake_zammad_client(settings_factory: Callable[..., ZammadAISettings]) -> FakeZammadClient:
    """Create a FakeZammadClient configured with Zammad API settings from test settings.

    Parameters:
        settings_factory (Callable[..., ZammadAISettings]): Factory that produces a ZammadAISettings instance; the returned settings' `zammad` attribute is used to configure the fake client.

    Returns:
        FakeZammadClient: A fake Zammad API client configured with `settings.zammad`.
    """
    settings = settings_factory()
    assert isinstance(settings.zammad, ZammadAPISettings)
    return FakeZammadClient(settings=settings.zammad)


@pytest.fixture
def test_client(
    monkeypatch: pytest.MonkeyPatch, settings_factory: Callable[..., ZammadAISettings]
) -> Generator[TestClient, None, None]:
    """Provide a TestClient for the backend application with settings and triage replaced for testing.

    Returns:
        TestClient: A TestClient for the backend application configured with the test settings and a triage stub.
    """
    import importlib

    settings = settings_factory()
    triage_stub = _ApiTriageStub()

    monkeypatch.setattr("app.settings.settings.get_settings", lambda: settings)
    monkeypatch.setattr("app.settings.get_settings", lambda: settings)

    import app.api.backend as backend_module

    backend_module = importlib.reload(backend_module)  # type: ignore
    monkeypatch.setattr(backend_module, "get_triage_service", lambda settings=None: triage_stub)

    with TestClient(backend_module.backend) as client:
        yield client
