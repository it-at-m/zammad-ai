"""Tests for answer middleware behavior."""

from types import SimpleNamespace
from typing import Any, cast

import pytest
from langchain.messages import HumanMessage, SystemMessage
from langchain_core.documents import Document
from langchain_core.language_models.chat_models import BaseChatModel

from app.answer.middleware import KnowledgebaseQuery, build_knowledgebase_middleware


class FakeQueryModel:
    """Minimal chat model fake that records structured-output usage."""

    def __init__(self, result: object | None = None) -> None:
        """Initialize the fake query model."""
        self.schema: type[KnowledgebaseQuery] | None = None
        self.calls: list[list[object]] = []
        self.result: object = {"query": "Personalausweis beantragen"} if result is None else result

    def with_structured_output(self, schema: type[KnowledgebaseQuery]) -> "FakeQueryModel":
        """Record the requested schema and return the fake model."""
        self.schema = schema
        return self

    async def ainvoke(self, messages: list[object]) -> object:
        """Record the prompt messages and return a fixed query."""
        self.calls.append(messages)
        return self.result


class FakeQdrantClient:
    """Minimal Qdrant client fake returning one document."""

    def __init__(self) -> None:
        """Initialize the fake client with no recorded calls."""
        self.calls: list[dict[str, object]] = []

    async def asearch_documents(self, **kwargs: object) -> list[tuple[Document, float]]:
        """Record the search arguments and return a fixed document."""
        self.calls.append(kwargs)
        return [
            (
                Document(
                    page_content="Der Antrag ist online moglich.",
                    metadata={"title": "Personalausweis", "url": "https://example.com/ausweis"},
                ),
                0.91,
            )
        ]


@pytest.mark.asyncio
async def test_knowledgebase_middleware_injects_context_once() -> None:
    """Middleware should query KB once and reuse the cached context."""
    query_model = FakeQueryModel()
    middleware: Any = build_knowledgebase_middleware(cast(BaseChatModel, query_model))
    qdrant_client = FakeQdrantClient()
    runtime = SimpleNamespace(
        context=SimpleNamespace(qdrant_kb_client=qdrant_client, knowledgebase_context=None),
    )
    state = {"messages": [HumanMessage(content="Ich brauche einen Personalausweis.")]}

    result = await middleware.abefore_agent(state, runtime)

    assert query_model.schema is KnowledgebaseQuery
    assert len(query_model.calls) == 1
    prompt_message = cast(Any, query_model.calls[0][1])
    assert prompt_message.content.startswith("Generate a search query")
    assert qdrant_client.calls == [{"query": "Personalausweis beantragen"}]
    assert result is not None
    message = result["messages"][0]
    assert isinstance(message, SystemMessage)
    assert "Knowledge-base context" in message.content
    assert "Personalausweis" in message.content
    assert "https://example.com/ausweis" in message.content
    assert runtime.context.knowledgebase_context == message.content
    assert "Der Antrag ist online moglich." in message.content

    second_result = await middleware.abefore_agent(state, runtime)

    assert second_result is None
    assert len(qdrant_client.calls) == 1


@pytest.mark.asyncio
async def test_knowledgebase_middleware_rejects_invalid_fallback_query() -> None:
    """Invalid structured output should not reach Qdrant and should yield empty context."""
    query_model = FakeQueryModel(result={"query": "x" * 201})
    middleware: Any = build_knowledgebase_middleware(cast(BaseChatModel, query_model))
    qdrant_client = FakeQdrantClient()
    runtime = SimpleNamespace(
        context=SimpleNamespace(qdrant_kb_client=qdrant_client, knowledgebase_context=None),
    )
    state: dict[str, Any] = {"messages": []}

    result = await middleware.abefore_agent(state, runtime)

    assert query_model.schema is KnowledgebaseQuery
    assert len(query_model.calls) == 1
    assert qdrant_client.calls == []
    assert result is not None
    message = result["messages"][0]
    assert isinstance(message, SystemMessage)
    assert (
        message.content == "Knowledge-base context\n\nNo relevant knowledge-base documents were found for this request."
    )
    assert runtime.context.knowledgebase_context == message.content
