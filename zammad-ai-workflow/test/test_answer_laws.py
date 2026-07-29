"""Tests for law-specific answer retrieval tools."""

from collections.abc import Callable
from typing import Any

import pytest

from app.answer.knowledgebase import QdrantKBClient
from app.answer.laws import build_law_tool_name
from app.settings import ZammadAISettings


class FakeVectorStore:
    """Minimal vector store fake capturing async search arguments."""

    def __init__(self) -> None:
        """Initialize the fake with no captured arguments."""
        self.kwargs: dict[str, Any] | None = None

    async def asimilarity_search_with_relevance_scores(self, **kwargs: Any) -> list:
        """Capture async search arguments and return no results."""
        self.kwargs = kwargs
        return []


def test_build_law_tool_name_sanitizes_configured_law_id() -> None:
    """Configured law ids should produce model-compatible tool names."""
    assert build_law_tool_name("FeV 2010") == "search_law_fev_2010"


def test_answer_context_contains_configured_law_tool(
    settings_factory: Callable[..., ZammadAISettings],
) -> None:
    """Prompt context should list one dedicated tool per configured law."""
    from app.settings.answer import LawToolSettings
    from app.utils.context_builders import build_answer_context

    settings = settings_factory()
    settings.answer.laws = [LawToolSettings(id="fev", name="Fahrerlaubnis-Verordnung")]

    context = build_answer_context(settings.answer)

    assert {
        "name": "search_law_fev",
        "description": "Search indexed legal text from Fahrerlaubnis-Verordnung (law_id: fev)",
    } in context["available_tools"]


@pytest.mark.asyncio
async def test_asearch_law_documents_filters_by_law_metadata() -> None:
    """Law retrieval should be scoped to law source and law_id metadata."""
    client = QdrantKBClient.__new__(QdrantKBClient)
    client.qdrant_settings = type("Settings", (), {"retrieval_num_documents": 5})()
    client.vectorstore = FakeVectorStore()

    result = await client.asearch_law_documents(law_id="fev", query="Probe", k=3, offset=2)

    assert result == []
    captured_kwargs = client.vectorstore.kwargs
    assert captured_kwargs is not None
    assert captured_kwargs["query"] == "Probe"
    assert captured_kwargs["k"] == 3
    assert captured_kwargs["offset"] == 2
    search_filter = captured_kwargs["filter"]
    assert [condition.key for condition in search_filter.must] == ["metadata.source", "metadata.law_id"]
    assert [condition.match.value for condition in search_filter.must] == ["law", "fev"]
