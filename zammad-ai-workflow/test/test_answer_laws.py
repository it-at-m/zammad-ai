"""Tests for law-specific answer retrieval tools."""

from collections.abc import Callable
from typing import Any

import pytest
from langchain_core.documents import Document

from app.answer.knowledgebase import QdrantKBClient
from app.answer.laws import build_law_tool_name
from app.settings import ZammadAISettings
from app.settings.answer import MultiQuerySettings


class FakeVectorStore:
    """Minimal vector store fake capturing async search arguments."""

    def __init__(self) -> None:
        """Initialize the fake with no captured arguments."""
        self.kwargs: dict[str, Any] | None = None

    async def asimilarity_search_with_relevance_scores(self, **kwargs: Any) -> list:
        """Capture async search arguments and return no results."""
        self.kwargs = kwargs
        return []


class FakeMultiQueryRetriever:
    """Minimal multi-query retriever fake returning a fixed query set."""

    def __init__(self, queries: list[str]) -> None:
        self.queries = queries
        self.calls: list[tuple[str, Any]] = []

    async def agenerate_queries(self, question: str, run_manager: Any) -> list[str]:
        self.calls.append((question, run_manager))
        return self.queries


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
    client: Any = QdrantKBClient.__new__(QdrantKBClient)
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


@pytest.mark.asyncio
async def test_asearch_documents_excludes_law_points_by_default() -> None:
    """General KB retrieval should exclude law-indexed points by default (law_id absent).

    The default filter should require metadata.law_id to be null (i.e. the key
    does not exist) so that law chunks are not returned by general KB searches.
    """
    client: Any = QdrantKBClient.__new__(QdrantKBClient)
    client.qdrant_settings = type("Settings", (), {"retrieval_num_documents": 5})()  # type: ignore[assignment]
    client.vectorstore = FakeVectorStore()

    result = await client.asearch_documents(query="Test", k=4, offset=1)

    assert result == []
    captured_kwargs = client.vectorstore.kwargs
    assert captured_kwargs is not None
    assert captured_kwargs["query"] == "Test"
    assert captured_kwargs["k"] == 4
    assert captured_kwargs["offset"] == 1
    search_filter = captured_kwargs["filter"]
    # Expect a must clause checking metadata.law_id is empty (key does not exist)
    must = getattr(search_filter, "must", None)
    assert must is not None and len(must) == 1
    cond = must[0]
    # Using Qdrant's IsEmptyCondition which stores the inspected key on `is_empty.key`
    assert getattr(cond, "is_empty", None) is not None
    assert getattr(cond.is_empty, "key", None) == "metadata.law_id"


@pytest.mark.asyncio
async def test_asearch_documents_respects_explicit_filter() -> None:
    """If an explicit filter is provided, it should be used instead of the default."""
    client: Any = QdrantKBClient.__new__(QdrantKBClient)
    client.qdrant_settings = type("Settings", (), {"retrieval_num_documents": 5})()  # type: ignore[assignment]
    client.vectorstore = FakeVectorStore()

    # Build a simple explicit filter object (we don't need real qdrant types here)
    explicit_filter = object()

    result = await client.asearch_documents(query="Test2", k=2, offset=0, search_filter=explicit_filter)

    assert result == []
    captured_kwargs = client.vectorstore.kwargs
    assert captured_kwargs is not None
    assert captured_kwargs["filter"] is explicit_filter


@pytest.mark.asyncio
async def test_asearch_documents_returns_only_kb_article_from_vectorstore() -> None:
    """When the underlying vectorstore contains both a KB article and a law chunk, asearch_documents (with its default filter) should return only the KB article."""

    class FakeVectorStoreWithDocs:
        def __init__(self) -> None:
            self.kb_doc = Document(page_content="KB: How to reset password", metadata={"title": "Reset password"})
            self.law_doc = Document(page_content="LAW: §11 Eignung", metadata={"law_id": "fev", "source": "law"})

        async def asimilarity_search_with_relevance_scores(self, **kwargs: Any) -> list:
            # Inspect provided filter to decide which documents to return.
            f = kwargs.get("filter")
            # If the filter explicitly requires metadata.law_id to be empty,
            # emulate Qdrant by returning only the KB document.
            must = getattr(f, "must", None)
            if must:
                for cond in must:
                    # Accept both FieldCondition (used elsewhere) and IsEmptyCondition
                    if getattr(cond, "key", None) == "metadata.law_id" and getattr(cond, "is_null", None) is True:
                        return [(self.kb_doc, 0.9)]
                    if (
                        getattr(cond, "is_empty", None) is not None
                        and getattr(cond.is_empty, "key", None) == "metadata.law_id"
                    ):
                        return [(self.kb_doc, 0.9)]
            # Otherwise return both documents
            return [(self.kb_doc, 0.9), (self.law_doc, 0.5)]

    client: Any = QdrantKBClient.__new__(QdrantKBClient)
    client.qdrant_settings = type("Settings", (), {"retrieval_num_documents": 5})()  # type: ignore[assignment]
    client.vectorstore = FakeVectorStoreWithDocs()

    result = await client.asearch_documents(query="reset", k=5, offset=0)

    # Expect only the KB article to be returned
    assert isinstance(result, list)
    assert len(result) == 1
    doc, score = result[0]
    assert "KB:" in doc.page_content


@pytest.mark.asyncio
async def test_asearch_documents_expands_queries_when_multi_query_is_enabled() -> None:
    """Multi-query retrieval should fan out search queries and keep the best score per document."""

    class FakeVectorStoreMulti:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []
            self.doc_a = Document(page_content="A", metadata={"id": "a"})
            self.doc_b = Document(page_content="B", metadata={"id": "b"})
            self.doc_c = Document(page_content="C", metadata={"id": "c"})
            self.results = {
                "erste frage": [(self.doc_a, 0.4), (self.doc_b, 0.6)],
                "zweite frage": [(self.doc_a, 0.9), (self.doc_c, 0.5)],
                "originalfrage": [(self.doc_c, 0.7)],
            }

        async def asimilarity_search_with_relevance_scores(self, **kwargs: Any) -> list[tuple[Document, float]]:
            self.calls.append(kwargs)
            return self.results[kwargs["query"]]

    client: Any = QdrantKBClient.__new__(QdrantKBClient)
    client.qdrant_settings = type("Settings", (), {"retrieval_num_documents": 2})()  # type: ignore[assignment]
    client.multi_query_settings = MultiQuerySettings(enabled=True, include_original=True)  # type: ignore[assignment]
    client.multi_query_retriever = FakeMultiQueryRetriever(["erste frage", "zweite frage"])
    client.vectorstore = FakeVectorStoreMulti()

    result = await client.asearch_documents(query="originalfrage", k=2, offset=0, search_filter=object())

    assert [call["query"] for call in client.vectorstore.calls] == ["erste frage", "zweite frage", "originalfrage"]
    assert all(call["offset"] == 0 for call in client.vectorstore.calls)
    assert len(result) == 2
    assert result[0][0].page_content == "A"
    assert result[0][1] == 0.9
    assert result[1][0].page_content == "C"
    assert result[1][1] == 0.7
