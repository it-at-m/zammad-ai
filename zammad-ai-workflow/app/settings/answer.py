"""Settings for answer generation, knowledge base, and DLF integrations."""

from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    Field,
    FilePath,
    HttpUrl,
    NonNegativeInt,
    PositiveInt,
    SecretStr,
    model_validator,
)

from app.utils.paths import get_prompts_dir
from app.utils.validators import validate_is_prompt

from .langfuse import LangfusePrompt


class StringPromptConfig(BaseModel):
    """Prompt configuration with a raw string template."""

    type: Literal["string"] = "string"
    prompt: str = Field(
        description="The prompt template as a raw string.",
        default="",
    )


class FilePromptConfig(BaseModel):
    """Prompt configuration loaded from a file."""

    type: Literal["file"] = "file"
    prompt: Annotated[FilePath, AfterValidator(func=validate_is_prompt)] = Field(
        description="The file path to the prompt template.",
    )


class LangfusePromptConfig(BaseModel):
    """Prompt configuration loaded from Langfuse."""

    type: Literal["langfuse"] = "langfuse"
    prompt: LangfusePrompt = Field(
        description="The name and label of the Langfuse prompt to use.",
    )


PromptSourceConfig = StringPromptConfig | FilePromptConfig | LangfusePromptConfig
# Note: All prompt sources support Jinja2 templating automatically.
# If a prompt contains Jinja2 syntax ({{ variables }}, {% conditionals %}, etc.),
# it will be automatically rendered with the appropriate context.


class JudgeSettings(BaseModel):
    """Settings for LLM judge evaluation of generated answers."""

    enabled: bool = Field(
        default=False,
        description="Whether to run an LLM judge after answer generation.",
    )
    prompt: PromptSourceConfig = Field(
        description="Prompt configuration for the judge evaluation step.",
        default_factory=lambda: FilePromptConfig(
            prompt=get_prompts_dir() / "judge" / "judge.prompt.md",
        ),
        discriminator="type",
    )
    repair_prompt: PromptSourceConfig = Field(
        description="Prompt configuration used to instruct the answer agent during a repair pass.",
        default_factory=lambda: FilePromptConfig(
            prompt=get_prompts_dir() / "answer" / "repair.prompt.md",
        ),
        discriminator="type",
    )
    max_repairs: NonNegativeInt = Field(
        default=0,
        description="Maximum number of repair passes to attempt after a failed judgment.",
    )


class MultiQuerySettings(BaseModel):
    """Settings for optional multi-query retrieval expansion."""

    enabled: bool = Field(
        default=False,
        description="Whether to expand each retrieval query into multiple semantically similar queries.",
    )
    include_original: bool = Field(
        default=True,
        description="Whether to include the original query alongside generated variants.",
    )


class QdrantSettings(BaseModel):
    """Settings for Qdrant vector database integration, including host URL, API key, collection name, and vector configuration."""

    url: HttpUrl = Field(
        description="Qdrant host URL",
        default=HttpUrl(url="http://localhost:6333"),
        examples=["https://qdrant.example.com:6333"],
    )
    api_key: SecretStr | None = Field(
        description="Qdrant API key; always use API keys in production for secure access",
        default=None,
        examples=["sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"],
    )
    collection_name: str = Field(
        description="Qdrant collection name",
        default="zammad-ai_default",
        examples=["zammad-ai_my-topic"],
    )
    vector_name: str = Field(
        description="Qdrant vector name (used for namespacing vectors, optional)",
        default="",
    )
    vector_dimension: PositiveInt = Field(
        description="Dimension of the embeddings stored in Qdrant",
        default=1024,
    )
    timeout: PositiveInt = Field(
        description="Timeout in seconds for Qdrant client operations",
        default=60,
    )
    retrieval_num_documents: PositiveInt = Field(
        description="The number of relevant documents to retrieve for each search query.",
        default=5,
    )
    retrieval_mode: Literal["dense", "sparse", "hybrid"] = Field(
        description="Optional: Can be dense, sparse or hybrid. When sparse or hybrid is used, a sparse embedding implementation must be available in the environment.",
        default="hybrid",
    )
    sparse_vector_name: str = Field(
        description="Optional: Name of the sparse vector",
        default="sparse",
    )
    multi_query: MultiQuerySettings = Field(
        default_factory=MultiQuerySettings,
        description="Optional multi-query expansion settings for Qdrant retrieval.",
    )


class LawToolSettings(BaseModel):
    """Settings for exposing one indexed law as an answer-agent tool."""

    id: str = Field(
        description="Stable identifier of the indexed law, matching the law_id metadata in Qdrant.",
        examples=["fev", "stvg"],
        min_length=1,
    )
    name: str = Field(
        description="Human-readable name of the law used in tool descriptions.",
        examples=["Fahrerlaubnis-Verordnung"],
        min_length=1,
    )


class DLFSettings(BaseModel):
    """Settings for the Dienstleistungsfinder (DLF) integration."""

    url: HttpUrl = Field(
        description="The base URL of the DLF API.",
    )
    filter_categories: list[str] = Field(
        description="List of categories to filter DLF results. If empty, no category filtering will be applied.",
        default_factory=list,
    )
    timeout: PositiveInt = Field(
        description="Timeout in seconds for requests to the DLF API.",
        default=60,
    )
    max_retries: PositiveInt = Field(
        description="Maximum number of retries for DLF API requests in case of transient failures.",
        default=2,
    )


class AnswerSettings(BaseModel):
    """Settings for the answer-generation pipeline."""

    agent_prompt: PromptSourceConfig = Field(
        description="Prompt configuration for the answer generation agent. Can be provided as a raw string, a file path, or a Langfuse prompt reference.",
        default_factory=lambda: FilePromptConfig(
            prompt=get_prompts_dir() / "answer" / "agent.prompt.md",
        ),
        discriminator="type",
    )
    format_prompt: PromptSourceConfig = Field(
        description="Prompt configuration for formatting the answer agent's responses. Can be provided as a raw string, a file path, or a Langfuse prompt reference.",
        default_factory=lambda: FilePromptConfig(
            prompt=get_prompts_dir() / "answer" / "format.prompt.md",
        ),
        discriminator="type",
    )

    dlf: DLFSettings | None = Field(
        default=None,
    )
    qdrant: QdrantSettings = Field(
        default=QdrantSettings(),
    )
    laws: list[LawToolSettings] = Field(
        default_factory=list,
        description="Indexed laws to expose as separate retrieval tools. Each id must match Qdrant metadata law_id.",
    )
    judge: JudgeSettings = Field(
        default_factory=JudgeSettings,
    )
    ai_answer_disclaimer: str = Field(
        description="Disclaimer text to append to all generated answers, for example to indicate that the answer was generated by an AI and may not be accurate. This can be used to mitigate potential risks of incorrect information being provided to users.",
        default="",
    )

    @model_validator(mode="after")
    def validate_law_tool_name_uniqueness(self) -> "AnswerSettings":
        """Validate that every configured law produces a unique tool name.

        The tool name is produced with build_law_tool_name and may collide
        after case-normalization and 64-character truncation. Reject the
        configuration during model validation if any collisions are found.
        """
        from app.answer.laws import build_law_tool_name

        tool_name_map: dict[str, list[str]] = {}
        for law in self.laws:
            tool_name = build_law_tool_name(law.id)
            tool_name_map.setdefault(tool_name, []).append(law.id)

        # Find tool names that are produced by more than one law id
        conflicts = {name: ids for name, ids in tool_name_map.items() if len(ids) > 1}
        if conflicts:
            # Report the conflicting tool name and the law ids that produced it
            conflict_lines = [f"{name}: {ids}" for name, ids in sorted(conflicts.items())]
            raise ValueError(
                "Duplicate law tool names after normalization/truncation; conflicting mappings:\n"
                + "\n".join(conflict_lines)
            )

        return self
