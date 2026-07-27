"""LangChain integration helpers."""

import json
from typing import Any, TypeVar, cast

from langchain.messages import HumanMessage
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
    types_to_try = (
        expected_type
        if isinstance(expected_type, tuple)
        else (expected_type,)
    )

    # Prefer LangChain's explicit structured response when available.
    structured_response = agent_result.get("structured_response")

    if structured_response is not None:
        if not isinstance(structured_response, expected_type):
            raise TypeError(
                "LangChain agent returned an unexpected "
                "structured_response type."
            )

        return cast(T, structured_response)

    # Fallback: Some LangChain runtimes return raw messages where the final
    # assistant message contains a JSON-serialized structured response.
    messages = agent_result.get("messages") or []
    validation_errors: list[str] = []

    for message in reversed(messages):
        content: str | None = None

        # Raw strings have no trusted assistant provenance.
        if isinstance(message, str):
            continue

        if isinstance(message, dict):
            role = (
                message.get("role")
                or message.get("author")
                or message.get("sender")
                or message.get("type")
            )

            if not (
                isinstance(role, str)
                and role.lower() in ("assistant", "ai")
            ):
                continue

            raw_content = message.get("content")

            if isinstance(raw_content, str):
                content = raw_content

        else:
            # Explicitly skip human-originated LangChain messages.
            if isinstance(message, HumanMessage):
                continue

            role = (
                getattr(message, "role", None)
                or getattr(message, "type", None)
            )

            if not (
                isinstance(role, str)
                and role.lower() in ("assistant", "ai")
            ):
                continue

            raw_content = getattr(message, "content", None)

            if isinstance(raw_content, str):
                content = raw_content

        if not content or not content.strip():
            continue

        parsed: Any | None = None

        # First try parsing the entire content as JSON.
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            # Otherwise, try extracting a JSON object from surrounding text.
            start = content.find("{")
            end = content.rfind("}")

            if start != -1 and end > start:
                try:
                    parsed = json.loads(content[start : end + 1])
                except json.JSONDecodeError:
                    parsed = None

        if parsed is None:
            continue

        for target_type in types_to_try:
            try:
                if (
                    isinstance(target_type, type)
                    and issubclass(target_type, BaseModel)
                ):
                    value_to_validate = parsed

                    if isinstance(parsed, dict):
                        # Use a separate copy for each candidate model.
                        value_to_validate = parsed.copy()

                        model_fields = target_type.model_fields

                        # These defaults are used only for manually recovered
                        # responses, never for explicit structured responses.
                        if "documents" in model_fields:
                            value_to_validate.setdefault("documents", [])

                        if "auto_publish" in model_fields:
                            value_to_validate["auto_publish"] = False

                    return cast(
                        T,
                        target_type.model_validate(value_to_validate),
                    )

                if isinstance(parsed, target_type):
                    return cast(T, parsed)

            except ValidationError as exc:
                validation_errors.append(
                    f"{target_type.__name__}:\n{exc}"
                )

    expected_names = ", ".join(
        getattr(target_type, "__name__", repr(target_type))
        for target_type in types_to_try
    )

    if validation_errors:
        details = "\n\n".join(validation_errors)
    else:
        details = (
            "No parseable JSON was found in an assistant message."
        )

    raise ValueError(
        "LangChain agent returned no valid structured response. "
        f"Expected one of: {expected_names}.\n\n"
        f"{details}"
    )