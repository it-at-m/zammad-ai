"""Settings for Jinja2 prompt templating contexts.

This module provides Pydantic models for documenting the context variables
available for Jinja2 template rendering in different workflows.
"""

from typing import Any

from pydantic import BaseModel, Field


class ToolDefinition(BaseModel):
    """Definition of a tool for the answer workflow.

    This model represents a tool that can be used by the answer generation
    agent, including its name and description.

    Attributes:
        name: Unique identifier for the tool.
        description: Human-readable description of what the tool does.
    """

    name: str = Field(description="Unique identifier for the tool.")
    description: str = Field(description="Human-readable description of what the tool does.")


class TriageTemplateContext(BaseModel):
    """Context variables for triage prompt templates.

    These variables are automatically available in triage prompts that use Jinja2 syntax.
    They are populated from application settings and the list of categories.

    Attributes:
        knowledge_base_enabled: Whether knowledge base search is enabled.
        dlf_enabled: Whether DLF (Dienstleistungsfinder) search is enabled.
        no_category_name: Name of the fallback category.
        no_action_name: Name of the fallback action.
        categories: List of categories with name and auto_publish status.
    """

    knowledge_base_enabled: bool = Field(
        default=True,
        description="Whether knowledge base search is enabled.",
    )
    dlf_enabled: bool = Field(
        default=False,
        description="Whether DLF (Dienstleistungsfinder) search is enabled.",
    )
    no_category_name: str = Field(
        default="Cannot Categorize",
        description="Name of the fallback category.",
    )
    no_action_name: str = Field(
        default="no_action",
        description="Name of the fallback action.",
    )
    categories: list[dict[str, Any]] = Field(
        default_factory=list,
        description="List of categories with their properties (name, auto_publish, etc.).",
    )


class AnswerTemplateContext(BaseModel):
    """Context variables for answer prompt templates.

    These variables are automatically available in answer prompts that use Jinja2 syntax.
    They describe the available tools and configuration for answer generation.

    Attributes:
        available_tools: List of tools available for answer generation.
        knowledge_base_enabled: Whether knowledge base search is enabled.
        dlf_enabled: Whether DLF (Dienstleistungsfinder) search is enabled.
        retrieval_num_documents: Number of documents to retrieve for context.
    """

    available_tools: list[ToolDefinition] = Field(
        default_factory=list,
        description="List of tools available for answer generation.",
    )
    knowledge_base_enabled: bool = Field(
        default=True,
        description="Whether knowledge base search is enabled.",
    )
    dlf_enabled: bool = Field(
        default=False,
        description="Whether DLF (Dienstleistungsfinder) search is enabled.",
    )
    retrieval_num_documents: int = Field(
        default=5,
        description="Number of documents to retrieve for context.",
        ge=1,
        le=20,
    )


class JudgeTemplateContext(BaseModel):
    """Context variables for judge prompt templates.

    These variables are automatically available in judge prompts that use Jinja2 syntax.
    They configure the evaluation criteria and behavior.

    Attributes:
        thresholds: Score thresholds for each evaluation dimension.
        repair_enabled: Whether automatic repair of failed answers is enabled.
        max_repairs: Maximum number of repair attempts.
    """

    thresholds: dict[str, float] = Field(
        description="Score thresholds for each evaluation dimension (context_relevance, groundedness, answer_relevance).",
        default_factory=dict,
    )
    repair_enabled: bool = Field(
        default=False,
        description="Whether automatic repair of failed answers is enabled.",
    )
    max_repairs: int = Field(
        default=0,
        description="Maximum number of repair attempts.",
        ge=0,
        le=5,
    )
