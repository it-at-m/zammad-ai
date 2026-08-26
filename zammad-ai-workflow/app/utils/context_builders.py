"""Utilities for building Jinja2 template contexts from application settings.

This module provides functions to construct context dictionaries for Jinja2
prompt templates based on application configuration. It centralizes the
logic for extracting relevant configuration and formatting it appropriately
for template consumption.

The key insight: Jinja2 is used for STATIC configuration (enabled features,
thresholds, tool lists) while LangChain variables (like {text}, {categories})
are used for PER-REQUEST data.
"""

from datetime import date
from typing import Any

from app.answer.laws import build_law_tool_name
from app.models.triage import Category
from app.settings import ZammadAISettings
from app.settings.answer import AnswerSettings
from app.settings.templates import ToolDefinition


def build_triage_context(
    settings: ZammadAISettings,
    categories: list[Category],
) -> dict[str, Any]:
    """Build context dictionary for triage templates.

    Constructs a context dictionary with all variables needed for rendering
    triage-related Jinja2 templates. This includes static configuration from
    answer settings (KB enabled, DLF enabled) and triage settings (fallback
    category/action names).

    Note: Per-request data like role_description, categories_prompt, examples
    are still passed as LangChain variables in the existing workflow.

    Args:
        settings: Application settings containing triage and other configurations.
        categories: List of triage categories to include in the context.

    Returns:
        Dictionary with variables for Jinja2 rendering:
        - knowledge_base_enabled: bool
        - dlf_enabled: bool
        - no_category_name: str
        - no_action_name: str
        - categories: list of dicts with name and auto_publish

    Example:
        >>> from app.settings import get_settings
        >>> settings = get_settings()
        >>> context = build_triage_context(settings, categories)
        >>> # Pass to Jinja2 renderer
        >>> renderer.render_template(triage_prompt, context)
    """
    today: date = date.today()
    today_str: str = f"{today.isoformat()}, {today.strftime('%A')}, KW{today.isocalendar().week:02d}"
    return {
        "knowledge_base_enabled": bool(settings.answer.qdrant.collection_name),
        "dlf_enabled": settings.answer.dlf is not None,
        "no_category_name": settings.triage.no_category_name,
        "no_action_name": settings.triage.no_action_name,
        "categories": [
            {
                "name": c.name,
                "auto_publish": c.auto_publish,
            }
            for c in categories
        ],
        # Provide today's date (ISO format + weekday + calendar week) for prompts that need to reference the current day
        "today": today_str,
    }


def build_answer_context(
    settings: AnswerSettings,
) -> dict[str, Any]:
    """Build context dictionary for answer templates.

    Constructs a context dictionary with all variables needed for rendering
    answer-related Jinja2 templates. This includes available tools based on
    the configured integrations (Qdrant, DLF).

    Args:
        settings: Answer settings containing configuration for tools and
            integrations.

    Returns:
        Dictionary with variables for Jinja2 rendering:
        - available_tools: list of ToolDefinition objects
        - knowledge_base_enabled: bool
        - dlf_enabled: bool
        - retrieval_num_documents: int

    Example:
        >>> context = build_answer_context(settings.answer)
        >>> renderer.render_template(agent_prompt, context)
    """
    tools = _build_tool_definitions(settings)

    today: date = date.today()
    today_str: str = f"{today.isoformat()}, {today.strftime('%A')}, KW{today.isocalendar().week:02d}"

    return {
        "available_tools": [{"name": tool.name, "description": tool.description} for tool in tools],
        "knowledge_base_enabled": bool(settings.qdrant.collection_name),
        "dlf_enabled": settings.dlf is not None,
        "retrieval_num_documents": settings.qdrant.retrieval_num_documents,
        # Provide today's date (ISO format + weekday + calendar week) for prompts that need to reference the current day
        "today": today_str,
    }


def build_judge_context(
    settings: ZammadAISettings,
) -> dict[str, Any]:
    """Build context dictionary for judge templates.

    Constructs a context dictionary with all variables needed for rendering
    judge-related Jinja2 templates. This includes evaluation thresholds and
    repair configuration.

    Args:
        settings: Application settings containing judge configuration.

    Returns:
        Dictionary with variables for Jinja2 rendering:
        - thresholds: dict with context_relevance, groundedness, answer_relevance
        - repair_enabled: bool
        - max_repairs: int

    Example:
        >>> context = build_judge_context(settings)
        >>> renderer.render_template(judge_prompt, context)
    """
    judge_settings = settings.answer.judge

    today: date = date.today()
    today_str: str = f"{today.isoformat()}, {today.strftime('%A')}, KW{today.isocalendar().week:02d}"

    return {
        "thresholds": {
            "context_relevance": judge_settings.thresholds.context_relevance,
            "groundedness": judge_settings.thresholds.groundedness,
            "answer_relevance": judge_settings.thresholds.answer_relevance,
        },
        "repair_enabled": judge_settings.enabled and judge_settings.max_repairs > 0,
        "max_repairs": judge_settings.max_repairs,
        # Provide today's date (ISO format + weekday + calendar week) for prompts that need to reference the current day
        "today": today_str,
    }


def _build_tool_definitions(settings: AnswerSettings) -> list[ToolDefinition]:
    """Build list of tool definitions based on configured integrations.

    Args:
        settings: Answer settings.

    Returns:
        List of ToolDefinition objects for enabled tools.
    """
    tools = []

    # Knowledge base search tool (Qdrant)
    if settings.qdrant.collection_name:
        tools.append(
            ToolDefinition(
                name="search_internal_knowledgebase",
                description=(
                    f"Query the internal knowledgebase for policies, procedures, "
                    f"and detailed information (collection: {settings.qdrant.collection_name})"
                ),
            )
        )

    # DLF tool
    if settings.dlf:
        tools.append(
            ToolDefinition(
                name="search_website",
                description=f"Search the Dienstleistungsfinder API at {settings.dlf.url}",
            )
        )

    for law in settings.laws:
        tools.append(
            ToolDefinition(
                name=build_law_tool_name(law.id),
                description=f"Search indexed legal text from {law.name} (law_id: {law.id})",
            )
        )

    return tools


def merge_contexts(
    base: dict[str, Any],
    overrides: dict[str, Any],
) -> dict[str, Any]:
    """Merge two context dictionaries, with overrides taking precedence.

    This is useful for combining default contexts with runtime-specific overrides.

    Args:
        base: Base context dictionary.
        overrides: Override context dictionary.

    Returns:
        Merged dictionary with overrides applied.
    """
    result = base.copy()
    result.update(overrides)
    return result
