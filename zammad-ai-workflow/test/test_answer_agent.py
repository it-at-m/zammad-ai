"""Tests for answer agent wiring."""

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from langchain_core.documents import Document

from app.answer.agent import build_agent, search_knowledgebase
from app.answer.knowledgebase import KBDocument
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


@pytest.mark.asyncio
async def test_search_knowledgebase_returns_article_ids_without_urls() -> None:
    """KB tool should expose article IDs only and never leak stored URLs to the agent."""
    fake_client = SimpleNamespace(
        asearch_documents=AsyncMock(
            return_value=[
                (
                    Document(
                        page_content="Inhalt",
                        metadata={
                            "answer_title": "Titel",
                            "answer_body": "Inhalt",
                            "answer_id": 42,
                            "answer_url": "https://internal.example.com/#knowledge_base/1/locale/de-de/answer/42",
                        },
                    ),
                    0.9,
                )
            ]
        )
    )
    runtime = SimpleNamespace(context=SimpleNamespace(qdrant_kb_client=fake_client))

    result = await search_knowledgebase.coroutine(  # ty: ignore
        runtime=runtime,
        query="frage",
        num_documents=1,
        offset=0,
    )

    fake_client.asearch_documents.assert_awaited_once_with(query="frage", k=1, offset=0)
    document, score = result.documents_with_relevance_score[0]
    assert isinstance(document, KBDocument)
    assert document.id == 42
    assert document.title == "Titel"
    assert document.body == "Inhalt"
    assert score == 0.9
    assert "internal.example.com" not in result.model_dump_json()
