"""LangChain integration helpers."""

from typing import Any, TypeVar, cast

from langchain_core.runnables import RunnableConfig

T = TypeVar("T")

DEFAULT_RECURSION_LIMIT = 10


def with_recursion_limit(config: RunnableConfig, limit: int = DEFAULT_RECURSION_LIMIT) -> RunnableConfig:
    """Return a RunnableConfig with a bounded LangGraph recursion limit."""
    return RunnableConfig({**config, "recursion_limit": limit})


def extract_structured_response(
    agent_result: dict[str, Any],
    expected_type: type[T] | tuple[type[Any], ...],
) -> T:
    """Return LangChain's validated structured response from an agent result."""
    if "structured_response" not in agent_result:
        raise ValueError("LangChain agent result did not contain a structured_response.")

    structured_response = agent_result["structured_response"]
    if structured_response is None:
        raise ValueError("LangChain agent returned an empty structured_response.")

    if not isinstance(structured_response, expected_type):
        raise TypeError("LangChain agent returned an unexpected structured_response type.")

    return cast(T, structured_response)
