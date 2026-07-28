"""Helpers for answer-agent law retrieval tools."""

import re


def build_law_tool_name(law_id: str) -> str:
    """Build an OpenAI-compatible tool name for a configured law id."""
    normalized_law_id = re.sub(r"[^a-zA-Z0-9_-]+", "_", law_id).strip("_").lower()
    if not normalized_law_id:
        normalized_law_id = "unknown"
    return f"search_law_{normalized_law_id}"[:64]
