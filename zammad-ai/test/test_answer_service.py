from collections.abc import Awaitable, Callable
from unittest.mock import AsyncMock

import pytest

from app.answer import service as answer_module
from app.answer.judge import JudgeResult
from app.answer.service import AnswerService
from app.models.answer import DocumentDict, StructuredAgentResponse
from app.settings import ZammadAISettings
from app.settings.answer import JudgeSettings, JudgeThresholds, StringPromptConfig


class FakePromptTemplate:
    def format(self, *, user_text: str, category: str) -> str:
        return f"category={category}; user_text={user_text}"


class FakeLangfuseClient:
    def generate_session_id(self) -> str:
        return "session-id"

    def build_config(self, session_id: str | None = None) -> dict:
        return {"session_id": session_id}


class FakeJudgeHandler:
    def __init__(self) -> None:
        self.judge_result: JudgeResult | None = None

    async def judge_answer(self, **_kwargs) -> JudgeResult:
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
    service.langfuse_client = FakeLangfuseClient()
    service.user_message_template = FakePromptTemplate()
    service.agent = AsyncMock()
    service.agent.ainvoke = ainvoke
    service.agent_context = object()
    service.judge_handler = None
    service.judge_settings = None
    return service


@pytest.mark.asyncio
async def test_generate_answer_in_progress_gauge_returns_to_baseline_on_success(
    settings_factory: Callable[..., ZammadAISettings],
) -> None:
    baseline = _get_answer_runs_in_progress_value()

    async def _ainvoke(*_args, **_kwargs) -> dict:
        return {"structured_response": {"answer": "ok"}}

    service = _build_answer_service(ainvoke=_ainvoke, settings_factory=settings_factory)

    await service.generate_answer(user_text="hello", category="general")

    assert _get_answer_runs_in_progress_value() == baseline


@pytest.mark.asyncio
async def test_generate_answer_in_progress_gauge_increments_while_running(
    settings_factory: Callable[..., ZammadAISettings],
) -> None:
    baseline = _get_answer_runs_in_progress_value()
    expected = baseline + 1

    async def _ainvoke(*_args, **_kwargs) -> dict:
        assert _get_answer_runs_in_progress_value() == expected
        return {"structured_response": {"answer": "ok"}}

    service = _build_answer_service(ainvoke=_ainvoke, settings_factory=settings_factory)

    await service.generate_answer(user_text="hello", category="general")

    assert _get_answer_runs_in_progress_value() == baseline


@pytest.mark.asyncio
async def test_generate_answer_runs_judge_and_returns_passed_answer() -> None:
    async def _ainvoke(*_args, **_kwargs) -> dict:
        return {
            "structured_response": StructuredAgentResponse(
                response="ok",
                documents=[DocumentDict(title="Source", url="https://example.com")],
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

    assert result.response == "ok"


@pytest.mark.asyncio
async def test_generate_answer_repairs_when_judge_fails() -> None:
    calls: list[list[str]] = []

    async def _ainvoke(*_args, **kwargs) -> dict:
        messages = kwargs["input"]["messages"]
        calls.append([message.content for message in messages])
        if len(calls) == 1:
            return {
                "structured_response": StructuredAgentResponse(
                    response="weak",
                    documents=[DocumentDict(title="Source", url="https://example.com")],
                )
            }
        return {
            "structured_response": StructuredAgentResponse(
                response="repaired",
                documents=[DocumentDict(title="Source", url="https://example.com")],
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

    assert result.response == "repaired"
    assert len(calls) == 2
