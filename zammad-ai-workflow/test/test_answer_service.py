"""Tests for answer service metrics behavior."""

import json
from collections.abc import Awaitable, Callable
from unittest.mock import AsyncMock

import pytest
from langchain.messages import HumanMessage

from app.answer import service as answer_module
from app.answer.judge import JudgeHandler, JudgeResult
from app.answer.service import AnswerService
from app.models.answer import AnswerCandidate, DocumentDict
from app.settings import ZammadAISettings
from app.settings.answer import JudgeSettings, JudgeThresholds, StringPromptConfig

VALID_RESPONSE = (
    "Dies ist eine ausreichend lange Testantwort fuer die Antwortgenerierung. "
    "Sie enthaelt genug Inhalt, um die konfigurierte Mindestlaenge des "
    "AnswerCandidate-Modells zu erfuellen und bleibt fuer die Assertions stabil."
)
REPAIRED_RESPONSE = (
    "Dies ist eine ausreichend lange reparierte Testantwort fuer die Antwortgenerierung. "
    "Sie enthaelt genug Inhalt, um die konfigurierte Mindestlaenge des "
    "AnswerCandidate-Modells zu erfuellen und bleibt fuer die Assertions stabil."
)


class FakePromptTemplate:
    """Minimal prompt template fake used by answer service tests."""

    def format(self, *, user_text: str, category: str) -> str:
        """Format deterministic prompt content for assertions."""
        return f"category={category}; user_text={user_text}"


class FakeLangfuseClient:
    """Minimal Langfuse client fake for session/config handling."""

    def __init__(self) -> None:
        """Initialize fake prompt tracking state."""
        self.last_langfuse_prompt: object | None = None

    def generate_session_id(self) -> str:
        """Return a deterministic session id."""
        return "session-id"

    def build_config(self, session_id: str | None = None, langfuse_prompt: object | None = None) -> dict:
        """Return a deterministic config payload for LangChain invocation."""
        self.last_langfuse_prompt = langfuse_prompt
        return {"session_id": session_id}


class FakeJudgeHandler:
    """Fake judge handler for testing answer service judge behavior."""

    def __init__(self) -> None:
        """Initialize fake judge handler with no judge result."""
        self.judge_result: JudgeResult | None = None

    async def judge_answer(self, **_kwargs) -> JudgeResult:
        """Return a judge result for testing answer service judge behavior.

        Returns the pre-configured judge result, or a passing result if none is set.

        Returns:
        -------
        JudgeResult
            The judge result for evaluation.
        """
        if self.judge_result is None:
            return JudgeResult(
                context_relevance=1.0,
                groundedness=1.0,
                answer_relevance=1.0,
                passed=True,
                reasoning="pass",
            )
        return self.judge_result


def _get_answer_runs_in_progress_value() -> float:
    for metric in answer_module.ANSWER_RUNS_IN_PROGRESS.collect():
        for sample in metric.samples:
            if sample.name == "zammad_ai_answer_runs_in_progress":
                return sample.value
    raise AssertionError("answer runs in-progress gauge sample not found")


def _build_answer_service(
    ainvoke: Callable[..., Awaitable[dict]],
    settings_factory: Callable[..., ZammadAISettings],
) -> AnswerService:
    service = AnswerService.__new__(AnswerService)
    service.settings = settings_factory(
        overrides={
            "answer": {
                "ai_answer_disclaimer": "",
            },
        }
    )
    service.langfuse_client = FakeLangfuseClient()  # ty: ignore
    service.user_message_template = FakePromptTemplate()  # ty: ignore
    service.agent = AsyncMock()
    service.agent.ainvoke = ainvoke
    service.agent_context = object()  # ty: ignore
    service.judge_handler = None
    service.judge_settings = None  # ty: ignore
    return service


@pytest.mark.asyncio
async def test_generate_answer_in_progress_gauge_returns_to_baseline_on_success(
    settings_factory: Callable[..., ZammadAISettings],
) -> None:
    """Gauge value should return to baseline after a successful answer run."""
    baseline = _get_answer_runs_in_progress_value()

    async def _ainvoke(*_args, **_kwargs) -> dict:
        return {
            "structured_response": AnswerCandidate(
                response=VALID_RESPONSE,
                documents=[],
                auto_publish=True,
            )
        }

    service = _build_answer_service(ainvoke=_ainvoke, settings_factory=settings_factory)
    service.agent_langfuse_prompt = object()  # ty: ignore

    await service.generate_answer(user_text="hello", category="general")

    assert _get_answer_runs_in_progress_value() == baseline
    assert getattr(service.langfuse_client, "last_langfuse_prompt") is service.agent_langfuse_prompt


@pytest.mark.asyncio
async def test_generate_answer_in_progress_gauge_increments_while_running(
    settings_factory: Callable[..., ZammadAISettings],
) -> None:
    """Gauge should be incremented while answer generation is in progress."""
    baseline = _get_answer_runs_in_progress_value()
    expected = baseline + 1

    async def _ainvoke(*_args, **_kwargs) -> dict:
        assert _get_answer_runs_in_progress_value() == expected
        return {
            "structured_response": AnswerCandidate(
                response=VALID_RESPONSE,
                documents=[],
                auto_publish=True,
            )
        }

    service = _build_answer_service(ainvoke=_ainvoke, settings_factory=settings_factory)

    await service.generate_answer(user_text="hello", category="general")

    assert _get_answer_runs_in_progress_value() == baseline


@pytest.mark.asyncio
async def test_generate_answer_runs_judge_and_returns_passed_answer() -> None:
    """Service should run judge and return answer when judge passes."""

    async def _ainvoke(*_args, **_kwargs) -> dict:
        return {
            "structured_response": AnswerCandidate(
                response=VALID_RESPONSE,
                documents=[DocumentDict(title="Source", url="https://example.com")],
                auto_publish=True,
            )
        }

    service = _build_answer_service(ainvoke=_ainvoke, settings_factory=ZammadAISettings)
    setattr(service, "judge_handler", FakeJudgeHandler())
    service.judge_settings = JudgeSettings(
        enabled=True,
        thresholds=JudgeThresholds(),
        prompt=StringPromptConfig(prompt="Judge the answer."),
        repair_prompt=StringPromptConfig(prompt="Repair: {repair_instructions}"),
        max_repairs=1,
    )

    result = await service.generate_answer(user_text="hello", category="general")

    assert isinstance(result, AnswerCandidate)
    assert result.response == VALID_RESPONSE


@pytest.mark.asyncio
async def test_generate_answer_repairs_when_judge_fails() -> None:
    """Service should repair answer when judge fails and return repaired response."""
    calls: list[list[str]] = []

    async def _ainvoke(*_args, **kwargs) -> dict:
        messages = kwargs["input"]["messages"]
        calls.append([message.content for message in messages])
        if len(calls) == 1:
            return {
                "structured_response": AnswerCandidate(
                    response=VALID_RESPONSE,
                    documents=[DocumentDict(title="Source", url="https://example.com")],
                    auto_publish=True,
                )
            }
        return {
            "structured_response": AnswerCandidate(
                response=REPAIRED_RESPONSE,
                documents=[DocumentDict(title="Source", url="https://example.com")],
                auto_publish=True,
            )
        }

    service = _build_answer_service(ainvoke=_ainvoke, settings_factory=ZammadAISettings)
    judge_handler = FakeJudgeHandler()
    judge_handler.judge_result = JudgeResult(
        context_relevance=0.1,
        groundedness=0.1,
        answer_relevance=0.1,
        passed=False,
        reasoning="not grounded",
        repair_instructions="add direct support from documents",
    )
    setattr(service, "judge_handler", judge_handler)
    service.judge_settings = JudgeSettings(
        enabled=True,
        thresholds=JudgeThresholds(),
        prompt=StringPromptConfig(prompt="Judge the answer."),
        repair_prompt=StringPromptConfig(prompt="Repair: {repair_instructions}"),
        max_repairs=1,
    )

    result = await service.generate_answer(user_text="hello", category="general")

    assert isinstance(result, AnswerCandidate)
    assert result.response == REPAIRED_RESPONSE
    assert len(calls) == 2


def test_judge_handler_builds_config_with_prompt_reference() -> None:
    """Judge traces should carry the Langfuse prompt reference when available."""
    handler = JudgeHandler.__new__(JudgeHandler)
    handler.langfuse_client = FakeLangfuseClient()  # ty: ignore
    handler.langfuse_prompt = object()  # ty: ignore

    _, config = handler._build_runnable_config(session_id="session-id")

    assert config["session_id"] == "session-id"  # ty: ignore
    assert getattr(handler.langfuse_client, "last_langfuse_prompt") is handler.langfuse_prompt


def test_extract_structured_response_ignores_human_json() -> None:
    """Ensure JSON embedded in a human message is not treated as an assistant reply.

    This prevents untrusted user-provided JSON from being interpreted as a
    structured agent output (AnswerCandidate / NoAnswerPossible).
    """
    from app.models.answer import AnswerCandidate, NoAnswerPossible
    from app.utils.langchain import extract_structured_response

    # Construct a payload that contains JSON inside a HumanMessage. The
    # extractor should ignore it because it's not assistant/AI-originated.
    candidate = {
        "response": VALID_RESPONSE,
        "documents": [],
        "auto_publish": True,
    }

    agent_result = {"messages": [HumanMessage(content=json.dumps(candidate))]}

    # When no assistant-originated structured response exists, the function
    # should not return a parsed AnswerCandidate/NoAnswerPossible. It will
    # therefore attempt to access agent_result["structured_response"] and
    # raise a KeyError.
    with pytest.raises(ValueError):
        extract_structured_response(agent_result, (AnswerCandidate, NoAnswerPossible))
