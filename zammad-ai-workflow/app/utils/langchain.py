"""LangChain integration helpers."""

import json
from typing import Any, TypeVar, cast

from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, ValidationError

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
    # Prefer the explicit structured_response when present
    if "structured_response" not in agent_result:
        # Fallback: some LangChain agent runtimes return raw messages where the
        # assistant's content contains the JSON serialized structured response.
        messages = agent_result.get("messages")
        if messages:
            # Prefer the last assistant/AI message
            for m in reversed(messages):
                # messages may be message objects or dicts
                content = None
                if isinstance(m, str):
                    content = m
                elif isinstance(m, dict):
                    content = m.get("content")
                else:
                    # message objects from langchain have attribute 'content'
                    content = getattr(m, "content", None)

                if not content or not isinstance(content, str):
                    continue

                # Try to parse JSON directly, otherwise attempt to extract a JSON
                # substring between the first '{' and the last '}' as a fallback.
                parsed = None
                try:
                    parsed = json.loads(content)
                except Exception:
                    try:
                        start = content.find("{")
                        end = content.rfind("}")
                        if start != -1 and end != -1 and end > start:
                            parsed = json.loads(content[start : end + 1])
                    except Exception:
                        parsed = None

                if parsed is None:
                    continue

                # Attempt to validate parsed object into one of the expected types
                types_to_try = expected_type if isinstance(expected_type, tuple) else (expected_type,)
                for t in types_to_try:
                    # If the target is a Pydantic model, use model_validate
                    try:
                        if isinstance(t, type) and issubclass(t, BaseModel):
                            return cast(T, t.model_validate(parsed))
                        # Otherwise, if the parsed object already matches the type, return it
                        if isinstance(parsed, t):
                            return cast(T, parsed)
                    except ValidationError:
                        # try next candidate type
                        continue

    structured_response = agent_result["structured_response"]
    if structured_response is None:
        raise ValueError("LangChain agent returned an empty structured_response.")

    if not isinstance(structured_response, expected_type):
        raise TypeError("LangChain agent returned an unexpected structured_response type.")

    return cast(T, structured_response)
