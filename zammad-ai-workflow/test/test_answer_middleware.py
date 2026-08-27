"""Tests for answer middleware behavior."""

from types import SimpleNamespace
from typing import Any, cast

import pytest
from langchain.messages import HumanMessage, SystemMessage
from langchain_core.documents import Document
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.runnables import RunnableLambda

from app.answer.middleware import KnowledgebaseQuery, _format_answer, build_knowledgebase_middleware
from app.models.answer import AnswerCandidate


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


@pytest.mark.asyncio
async def test_format_answer_links_langfuse_prompt_on_chat_prompt_template(monkeypatch: pytest.MonkeyPatch) -> None:
    """Formatting should attach the Langfuse prompt reference to the prompt template."""

    class FakeLangfuseClient:
        def __init__(self) -> None:
            self.last_langfuse_prompt: object | None = None

        def build_config(self, session_id: str | None = None, langfuse_prompt: object | None = None) -> dict[str, object]:
            self.last_langfuse_prompt = langfuse_prompt
            return {"session_id": session_id}

    class FakeStructuredModel:
        def __init__(self) -> None:
            self.calls: list[tuple[object, object]] = []

        async def _ainvoke(self, prompt_input: object, config: object | None = None) -> AnswerCandidate:
            self.calls.append((prompt_input, config))
            return AnswerCandidate(
                response=(
                    "Formatierte Antwort fuer den Test mit ausreichend Laenge, damit das "
                    "AnswerCandidate-Modell validiert werden kann und der Test die eigentliche "
                    "Verkettung zwischen Prompt-Template, strukturiertem Output und Langfuse-"
                    "Metadaten prueft, ohne an einer kuenstlich zu kurzen Mock-Antwort zu scheitern."
                ),
                documents=[],
                auto_publish=True,
            )

        def as_runnable(self) -> RunnableLambda:
            return RunnableLambda(self._ainvoke)

    class FakeChatModel:
        def __init__(self, structured_model: FakeStructuredModel) -> None:
            self.schema: type[AnswerCandidate] | None = None
            self.structured_model = structured_model

        def with_structured_output(self, schema: type[AnswerCandidate]) -> RunnableLambda:
            self.schema = schema
            return self.structured_model.as_runnable()

    class FakeChatPromptTemplate:
        last_instance: "FakeChatPromptTemplate | None" = None

        def __init__(self, messages: list[tuple[str, str]]) -> None:
            self.messages = messages
            self.metadata: dict[str, object] | None = None
            FakeChatPromptTemplate.last_instance = self

        def __or__(self, other: RunnableLambda) -> RunnableLambda:
            async def _ainvoke(prompt_input: object, config: object | None = None) -> AnswerCandidate:
                return await other.ainvoke(prompt_input, config=config) # ty: ignore

            return RunnableLambda(_ainvoke)

    monkeypatch.setattr("app.answer.middleware.ChatPromptTemplate", FakeChatPromptTemplate)

    structured_model = FakeStructuredModel()
    chat_model = FakeChatModel(structured_model)
    langfuse_client = FakeLangfuseClient()
    langfuse_prompt = object()
    response = AnswerCandidate(
        response="Lorem ipsum dolor sit amet, consectetur adipiscing elit. Sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat. Duis aute irure dolor in reprehenderit in voluptate velit esse cillum dolore eu fugiat nulla pariatur. Excepteur sint occaecat cupidatat non proident, sunt in culpa qui officia deserunt mollit anim id est laborum.",
        documents=[],
        auto_publish=True,
    )

    result = await _format_answer(
        chat_model=cast(BaseChatModel, chat_model),
        structured_response=response,
        langfuse_client=langfuse_client,
        format_prompt="Bitte formatiere die Antwort.",
        format_langfuse_prompt=langfuse_prompt,
        session_id="session-id",
    )

    assert chat_model.schema is AnswerCandidate
    assert isinstance(FakeChatPromptTemplate.last_instance, FakeChatPromptTemplate)
    assert FakeChatPromptTemplate.last_instance.messages == [
        ("system", "Bitte formatiere die Antwort."),
        ("human", "{answer_payload}"),
    ]
    assert FakeChatPromptTemplate.last_instance.metadata == {"langfuse_prompt": langfuse_prompt}
    assert len(structured_model.calls) == 1
    assert structured_model.calls[0][0] == {"answer_payload": response.model_dump_json(indent=2)}
    config = cast(dict[str, object], structured_model.calls[0][1])
    assert cast(dict[str, object], config["configurable"])["session_id"] == "session-id"
    assert langfuse_client.last_langfuse_prompt is None
    assert result.response.startswith("Formatierte Antwort fuer den Test")
