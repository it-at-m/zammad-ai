from collections.abc import Callable, Generator
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.models.triage import CategorizationResult, DaysSinceRequestResponse, ProcessingIdResponse
from app.models.zammad import ZammadArticle, ZammadTicket
from app.settings.triage import (
    ActionRule,
    Category,
    Condition,
    LangfusePrompt,
    LangfuseTriagePrompts,
    TriageSettings,
)
from app.triage import triage as triage_module
from app.triage.triage import TriageError, TriageService
from test.fakes import FakeGenAIHandler, FakeZammadClient, FakeZammadConnectionError


def test_triage_settings_rejects_invalid_references_and_missing_standard_answer() -> None:
    payload = {
        "categories": [{"name": "General"}, {"name": "Other"}],
        "no_category_name": "Unknown",
        "actions": [
            {"name": "No Action", "description": "No action", "type": "NoAction"},
            {"name": "Escalate", "description": "Escalate", "type": "StaticAnswer"},
        ],
        "no_action_name": "UnknownAction",
        "action_rules": [
            {
                "category_name": "MissingCategory",
                "action_name": "MissingAction",
                "conditions": [
                    {
                        "priority": 1,
                        "field": "days_since_request",
                        "operator": "greater_equals",
                        "value": 1,
                        "action_name": "MissingConditionAction",
                    }
                ],
            }
        ],
        "prompts": {
            "type": "string",
            "prompt_map": {
                "categories": "List of categories: {{categories}}",
                "examples": "Examples: {{examples}}",
                "role": "Role prompt",
            },
        },
    }

    with pytest.raises(ValidationError) as excinfo:
        TriageSettings.model_validate(payload)

    message = str(excinfo.value)
    assert "no_category_name 'Unknown'" in message
    assert "no_action_name 'UnknownAction'" in message
    assert "ActionRule.category_name 'MissingCategory'" in message
    assert "ActionRule.action_name 'MissingAction'" in message
    assert "Condition.action_name 'MissingConditionAction'" in message
    assert "Action 'Escalate' has type StaticAnswer but answer is None" in message


@pytest.mark.parametrize(
    ("prompts", "expected_type"),
    [
        (
            {
                "type": "string",
                "prompt_map": {
                    "categories": "List of categories: {{categories}}",
                    "examples": "Examples: {{examples}}",
                },
            },
            "string",
        ),
        (
            {
                "type": "file",
                "prompt_map": {
                    "categories": str(Path("categories.prompt.md")),
                    "examples": str(Path("examples.prompt.md")),
                },
            },
            "file",
        ),
        (
            {
                "type": "langfuse",
                "prompt_map": {
                    "categories": {"name": "drivers-licence/categories", "label": "latest"},
                    "examples": {"name": "drivers-licence/examples", "label": "latest"},
                },
            },
            "langfuse",
        ),
    ],
)
def test_triage_settings_rejects_prompt_maps_missing_required_keys(
    prompts: dict[str, Any],
    expected_type: str,
    tmp_path: Path,
) -> None:
    payload: dict[str, Any] = {
        "categories": [{"name": "General"}],
        "no_category_name": "General",
        "actions": [{"name": "No Action", "description": "No action", "type": "NoAction"}],
        "no_action_name": "No Action",
        "action_rules": [],
        "prompts": prompts,
    }

    if expected_type == "file":
        prompt_map = payload["prompts"]["prompt_map"]
        assert isinstance(prompt_map, dict)
        for key in ("categories", "examples"):
            prompt_path = tmp_path / f"{key}.prompt.md"
            prompt_path.write_text(f"{key} prompt", encoding="utf-8")
            prompt_map[key] = str(prompt_path)

    with pytest.raises(ValidationError) as excinfo:
        TriageSettings.model_validate(payload)

    message = str(excinfo.value)
    assert "missing required keys" in message
    assert "role" in message


def _get_triage_runs_in_progress_value() -> float:
    for metric in triage_module.TRIAGE_RUNS_IN_PROGRESS.collect():
        for sample in metric.samples:
            if sample.name == "zammad_ai_triage_runs_in_progress":
                return sample.value
    raise AssertionError("triage runs in-progress gauge sample not found")


@pytest.fixture
def patched_triage(
    monkeypatch: pytest.MonkeyPatch,
    settings_factory,
    fake_genai_handler: FakeGenAIHandler,
    fake_zammad_client: FakeZammadClient,
) -> Generator[TriageService, None, None]:
    """
    Provide a TriageService configured with test fakes for GenAI and Zammad.

    Parameters:
        monkeypatch (pytest.MonkeyPatch): Fixture used to patch the triage module's GenAIHandler, ZammadAPIClient, and ZammadConnectionError with the provided fakes.
        settings_factory: Callable that returns test settings used to construct the TriageService.
        fake_genai_handler (FakeGenAIHandler): Fake GenAI handler to be injected into the triage module.
        fake_zammad_client (FakeZammadClient): Fake Zammad client to be injected into the triage module.

    Returns:
        Generator[TriageService, None, None]: Yields a TriageService instance constructed with the test settings and wired to use the provided fakes.
    """
    monkeypatch.setattr(triage_module, "GenAIHandler", lambda *args, **kwargs: fake_genai_handler)
    monkeypatch.setattr(triage_module, "ZammadAPIClient", lambda *args, **kwargs: fake_zammad_client)
    monkeypatch.setattr(triage_module, "ZammadConnectionError", FakeZammadConnectionError)
    settings = settings_factory()
    triage = TriageService(settings=settings)
    yield triage


@pytest.fixture
def triage_factory(
    monkeypatch: pytest.MonkeyPatch,
    settings_factory,
    fake_genai_handler: FakeGenAIHandler,
    fake_zammad_client: FakeZammadClient,
) -> Callable[[list[ActionRule] | None], TriageService]:
    """
    Create a factory that produces TriageService instances configured with test fakes and optional action rules.

    Returns:
        factory (Callable[[list[ActionRule] | None], TriageService]): A callable that accepts an optional list of ActionRule and returns a TriageService built using the provided settings_factory and the patched fake GenAI and Zammad clients.
    """
    monkeypatch.setattr(triage_module, "GenAIHandler", lambda *args, **kwargs: fake_genai_handler)
    monkeypatch.setattr(triage_module, "ZammadAPIClient", lambda *args, **kwargs: fake_zammad_client)
    monkeypatch.setattr(triage_module, "ZammadConnectionError", FakeZammadConnectionError)

    def _factory(action_rules: list[ActionRule] | None = None) -> TriageService:
        """
        Create a TriageService configured with the given action rules.

        Parameters:
            action_rules (list[ActionRule] | None): Optional list of action rules to include in the service configuration; if None, default rules are used.

        Returns:
            TriageService: A TriageService instance configured with the provided action rules.
        """
        settings = settings_factory(action_rules=action_rules)
        return TriageService(settings=settings)

    return _factory


@pytest.mark.asyncio
async def test_perform_triage_returns_defaults_when_no_articles(patched_triage: TriageService) -> None:
    result = await patched_triage.perform_triage(id=123)
    assert result.category == patched_triage.no_category
    assert result.action == patched_triage.no_action
    assert result.reasoning == "No articles found"
    assert result.confidence == 1.0


@pytest.mark.asyncio
async def test_predict_category_falls_back_to_no_category(patched_triage: TriageService) -> None:
    patched_triage.genai_handler.categorization_result = CategorizationResult(  # type: ignore
        category=Category(name="Unknown-Invalid"),
        reasoning="mismatch",
        confidence=0.42,
    )
    result = await patched_triage.predict_category(message="some text", session_id="session-id")
    assert result.category == patched_triage.no_category
    assert "no_category" in result.reasoning
    assert result.confidence == 1.0


@pytest.mark.asyncio
async def test_get_action_id_uses_days_since_request_condition(triage_factory: Callable[[list[ActionRule] | None], TriageService]) -> None:
    action_rules = [
        ActionRule(
            category_name="General",
            action_name="No Action",
            conditions=[
                Condition(
                    priority=1,
                    field="days_since_request",
                    operator="greater_equals",
                    value=10,
                    action_name="AI_Answer",
                )
            ],
        )
    ]
    triage = triage_factory(action_rules)
    triage.genai_handler.days_since_request_response = DaysSinceRequestResponse(days_since_request=12, reason="ok")  # type: ignore
    categorization = CategorizationResult(
        category=Category(name="General"),
        reasoning="ok",
        confidence=0.8,
    )

    action_name = await triage.get_action_name(categorization_result=categorization, message="message", session_id="session-id")

    assert action_name == "AI_Answer"


@pytest.mark.asyncio
async def test_get_action_id_returns_no_action_for_no_category(patched_triage: TriageService) -> None:
    categorization = CategorizationResult(
        category=patched_triage.no_category,
        reasoning="no category",
        confidence=1.0,
    )

    action_name = await patched_triage.get_action_name(categorization_result=categorization, message="message", session_id="session-id")

    assert action_name == patched_triage.no_action.name


# ---------------------------------------------------------------------------
# perform_triage: happy path with articles
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_perform_triage_happy_path(patched_triage: TriageService) -> None:
    """Full triage with a ticket that has an article returns a real category and action."""
    patched_triage.zammad_client.ticket = ZammadTicket(  # type: ignore
        id=42,
        articles=[ZammadArticle(id=1, ticket_id=42, text="My printer is broken")],
    )
    patched_triage.genai_handler.categorization_result = CategorizationResult(  # type: ignore
        category=Category(name="General"),
        reasoning="hardware issue",
        confidence=0.9,
    )
    result = await patched_triage.perform_triage(id=42)
    assert result.category.name == "General"
    assert result.reasoning == "hardware issue"
    assert result.confidence == 0.9


@pytest.mark.asyncio
async def test_perform_triage_in_progress_gauge_returns_to_baseline_on_success(patched_triage: TriageService) -> None:
    """The in-progress gauge should return to baseline after a successful run."""
    baseline = _get_triage_runs_in_progress_value()
    patched_triage.zammad_client.ticket = ZammadTicket(  # type: ignore
        id=42,
        articles=[ZammadArticle(id=1, ticket_id=42, text="My printer is broken")],
    )
    patched_triage.genai_handler.categorization_result = CategorizationResult(  # type: ignore
        category=Category(name="General"),
        reasoning="hardware issue",
        confidence=0.9,
    )

    await patched_triage.perform_triage(id=42)

    assert _get_triage_runs_in_progress_value() == baseline


@pytest.mark.asyncio
async def test_perform_triage_in_progress_gauge_increments_while_running(patched_triage: TriageService) -> None:
    """The in-progress gauge should be incremented while perform_triage is executing."""
    baseline = _get_triage_runs_in_progress_value()
    expected = baseline + 1

    async def _get_ticket_and_assert_in_progress(id: int) -> ZammadTicket:
        assert _get_triage_runs_in_progress_value() == expected
        return ZammadTicket(
            id=id,
            articles=[ZammadArticle(id=1, ticket_id=id, text="My printer is broken")],
        )

    patched_triage.zammad_client.get_ticket = _get_ticket_and_assert_in_progress  # type: ignore
    patched_triage.genai_handler.categorization_result = CategorizationResult(  # type: ignore
        category=Category(name="General"),
        reasoning="hardware issue",
        confidence=0.9,
    )

    await patched_triage.perform_triage(id=42)

    assert _get_triage_runs_in_progress_value() == baseline


# ---------------------------------------------------------------------------
# perform_triage: Zammad connection error → TriageError
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_perform_triage_raises_triage_error_on_zammad_failure(patched_triage: TriageService) -> None:
    """A Zammad connection error should be wrapped in TriageError."""
    patched_triage.zammad_client.raise_connection_error = True  # type: ignore
    with pytest.raises(TriageError, match="Zammad connection error"):
        await patched_triage.perform_triage(id=99)


# ---------------------------------------------------------------------------
# predict_category: empty message
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_predict_category_empty_message(patched_triage: TriageService) -> None:
    """An empty (or whitespace-only) message returns no_category immediately."""
    result = await patched_triage.predict_category(message="   ", session_id="session-id")
    assert result.category == patched_triage.no_category
    assert "Empty message cannot be categorized" in result.reasoning
    assert result.confidence == 1.0


# ---------------------------------------------------------------------------
# predict_category: valid category keeps the prediction
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_predict_category_valid_category_kept(patched_triage: TriageService) -> None:
    """A valid category returned by GenAI is kept as-is."""
    patched_triage.genai_handler.categorization_result = CategorizationResult(  # type: ignore
        category=Category(name="General"),
        reasoning="looks right",
        confidence=0.88,
    )
    result = await patched_triage.predict_category(message="some text", session_id="session-id")
    assert result.category is not None
    assert result.category.name == "General"
    assert result.reasoning == "looks right"
    assert result.confidence == 0.88


# ---------------------------------------------------------------------------
# predict_category: GenAI handler raises → TriageError
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_predict_category_handles_genai_exception(patched_triage: TriageService) -> None:
    """An unexpected exception from the GenAI handler causes a TriageError."""

    async def _boom(*_args, **_kwargs):
        """
        Simulates a failing language model by immediately raising a RuntimeError.

        Always raises RuntimeError with the message "LLM exploded".
        Raises:
            RuntimeError: Indicates the simulated LLM failure ("LLM exploded").
        """
        raise RuntimeError("LLM exploded")

    patched_triage.genai_handler.categorize_ticket = _boom  # type: ignore
    with pytest.raises(TriageError) as excinfo:
        await patched_triage.predict_category(message="trigger error", session_id="session-id")
    assert "unexpected error" in str(excinfo.value)


@pytest.mark.asyncio
async def test_perform_triage_handles_processing_triage_error(patched_triage: TriageService) -> None:
    """A TriageError during processing in perform_triage is caught and returns a fallback result."""

    async def _boom(*_args, **_kwargs):
        """
        Always raises a TriageError to simulate a processing failure.

        Used in tests to force a processing error path.

        Raises:
            TriageError: Always raised with the message "Simulated processing error".
        """
        raise TriageError("Simulated processing error")

    # Mock predict_category to raise TriageError
    patched_triage.predict_category = _boom  # type: ignore

    # Ensure there is a ticket with articles so it doesn't return early
    patched_triage.zammad_client.ticket = ZammadTicket(id=123, articles=[ZammadArticle(id=1, ticket_id=123, text="Help me")])  # type: ignore

    result = await patched_triage.perform_triage(id=123)

    assert result.category == patched_triage.no_category
    assert result.action == patched_triage.no_action
    assert "Error during triage processing" in result.reasoning
    assert result.confidence == 1.0


# ---------------------------------------------------------------------------
# get_action_name: rule match without conditions -> use rule's action_name
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_action_id_rule_without_conditions(triage_factory: Callable[[list[ActionRule] | None], TriageService]) -> None:
    """A rule with no conditions directly returns the rule's action_id."""
    action_rules = [
        ActionRule(category_name="General", action_name="AI_Answer", conditions=None),
    ]
    triage = triage_factory(action_rules)
    categorization = CategorizationResult(
        category=Category(name="General"),
        reasoning="ok",
        confidence=0.8,
    )

    action_name = await triage.get_action_name(categorization_result=categorization, message="msg", session_id="s")
    assert action_name == "AI_Answer"


# ---------------------------------------------------------------------------
# get_action_name: condition NOT met -> falls through to rule's default action_name
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_action_id_condition_not_met_falls_through(triage_factory: Callable[[list[ActionRule] | None], TriageService]) -> None:
    """When a condition's operator check fails, the rule's default action_id is returned."""
    action_rules = [
        ActionRule(
            category_name="General",
            action_name="No Action",
            conditions=[
                Condition(priority=1, field="days_since_request", operator="greater_equals", value=10, action_name="AI_Answer"),
            ],
        ),
    ]
    triage = triage_factory(action_rules)
    # days=5 does NOT satisfy >=10
    triage.genai_handler.days_since_request_response = DaysSinceRequestResponse(days_since_request=5, reason="recent")  # type: ignore
    categorization = CategorizationResult(category=Category(name="General"), reasoning="ok", confidence=0.8)

    action_name = await triage.get_action_name(categorization_result=categorization, message="msg", session_id="s")
    assert action_name == "No Action"  # rule's default, not the condition's action_name


# ---------------------------------------------------------------------------
# get_action_name: processing_id condition match
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_action_id_processing_id_condition(triage_factory: Callable[[list[ActionRule] | None], TriageService]) -> None:
    """A processing_id condition that matches returns the condition's action_id."""
    action_rules = [
        ActionRule(
            category_name="General",
            action_name="No Action",
            conditions=[
                Condition(priority=1, field="processing_id", operator="equals", value="ABC", action_name="AI_Answer"),
            ],
        ),
    ]
    triage = triage_factory(action_rules)
    triage.genai_handler.processing_id_response = ProcessingIdResponse(processing_id="ABC", condition_met=True)  # type: ignore
    categorization = CategorizationResult(category=Category(name="General"), reasoning="ok", confidence=0.8)

    action_name = await triage.get_action_name(categorization_result=categorization, message="msg", session_id="s")
    assert action_name == "AI_Answer"


# ---------------------------------------------------------------------------
# get_action_name: no matching rule -> no_action
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_action_id_no_matching_rule(triage_factory: Callable[[list[ActionRule] | None], TriageService]) -> None:
    """When no action rule matches the category, no_action is returned."""
    # Rule only for different category name, but our categorization has category "General"
    action_rules = [
        ActionRule(category_name="Other", action_name="AI_Answer", conditions=None),
    ]
    triage = triage_factory(action_rules)
    categorization = CategorizationResult(category=Category(name="General"), reasoning="ok", confidence=0.8)

    action_name = await triage.get_action_name(categorization_result=categorization, message="msg", session_id="s")
    assert action_name == triage.no_action.name


def test_langfuse_prompt_map_values_are_typed() -> None:
    prompts = LangfuseTriagePrompts.model_validate(
        {
            "type": "langfuse",
            "prompt_map": {
                "categories": {"name": "drivers-licence/categories", "label": "latest"},
                "examples": {"name": "drivers-licence/examples", "label": "latest"},
                "role": {"name": "drivers-licence/role", "label": "latest"},
            },
        }
    )

    assert isinstance(prompts.prompt_map["categories"], LangfusePrompt)
    assert isinstance(prompts.prompt_map["examples"], LangfusePrompt)
    assert isinstance(prompts.prompt_map["role"], LangfusePrompt)


# ---------------------------------------------------------------------------
# get_action_name: condition priority ordering
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_action_id_respects_condition_priority(triage_factory: Callable[[list[ActionRule] | None], TriageService]) -> None:
    """Higher-priority (lower number) conditions are evaluated first."""
    action_rules = [
        ActionRule(
            category_name="General",
            action_name="No Action",
            conditions=[
                # priority=2 should be evaluated second
                Condition(priority=2, field="days_since_request", operator="greater_equals", value=1, action_name="Standardantwort"),
                # priority=1 should be evaluated first and match
                Condition(priority=1, field="days_since_request", operator="greater_equals", value=5, action_name="AI_Answer"),
            ],
        ),
    ]
    triage = triage_factory(action_rules)
    triage.genai_handler.days_since_request_response = DaysSinceRequestResponse(days_since_request=7, reason="ok")  # type: ignore
    categorization = CategorizationResult(category=Category(name="General"), reasoning="ok", confidence=0.8)

    action_name = await triage.get_action_name(categorization_result=categorization, message="msg", session_id="s")
    # priority=1 condition (>=5, action_name=KI_Antwort) fires first
    assert action_name == "AI_Answer"


# ---------------------------------------------------------------------------
# get_action_name: None category -> no_action
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_action_id_none_category(patched_triage: TriageService) -> None:
    """A None category always returns no_action."""
    categorization = CategorizationResult(category=None, reasoning="no cat", confidence=1.0)
    action_name = await patched_triage.get_action_name(categorization_result=categorization, message="msg", session_id="s")
    assert action_name == patched_triage.no_action.name


# ---------------------------------------------------------------------------
# _name_to_category / _name_to_action helpers
# ---------------------------------------------------------------------------


def test_name_to_category_known(patched_triage: TriageService) -> None:
    """Known category name returns the matching Category."""
    cat = patched_triage._name_to_category("General")
    assert cat.name == "General"


def test_name_to_category_unknown(patched_triage: TriageService) -> None:
    """Unknown category name returns no_category fallback."""
    cat = patched_triage._name_to_category("Unknown")
    assert cat == patched_triage.no_category


def test_name_to_action_known(patched_triage: TriageService) -> None:
    """Known action name returns the matching Action."""
    action = patched_triage._name_to_action("Escalate")
    assert action.name == "Escalate"


def test_name_to_action_unknown(patched_triage: TriageService) -> None:
    """Unknown action name returns no_action fallback."""
    action = patched_triage._name_to_action("Unknown")
    assert action == patched_triage.no_action
