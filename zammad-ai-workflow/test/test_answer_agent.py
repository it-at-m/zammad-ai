"""Tests for answer agent wiring."""

from typing import Any

from app.answer.agent import build_agent
from app.settings.answer import LawToolSettings
from app.settings.genai import GenAIOpenAISettings


def test_build_agent_enables_expected_tool_failures(monkeypatch) -> None:
    """Answer tools should surface expected failures back to the agent."""
    captured: dict[str, Any] = {}
    sentinel = object()

    def fake_create_agent(**kwargs: Any) -> object:
        captured.update(kwargs)
        return sentinel

    monkeypatch.setattr("app.answer.agent.create_agent", fake_create_agent)
    monkeypatch.setattr("app.answer.agent.get_chat_model", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(
        "app.answer.agent.build_knowledgebase_middleware",
        lambda *_args, **_kwargs: object(),
    )

    result = build_agent(
        genai_settings=GenAIOpenAISettings(),
        agent_prompt="system prompt",
        dlf_enabled=True,
        laws=[LawToolSettings(id="fev", name="Fahrerlaubnis-Verordnung")],
    )

    assert result is sentinel
    tools = captured["tools"]
    assert [tool.handle_tool_error for tool in tools] == [True, True, True]
