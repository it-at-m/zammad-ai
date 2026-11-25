"""Settings model for indexing into multiple Qdrant collections."""

from typing import Any

from pydantic import BaseModel, Field, model_validator

from .law import LawConfig


class IndexTargetSettings(BaseModel):
    """Overrides for one indexing target.

    A target describes one Qdrant collection together with the Zammad
    knowledge base content and law sources that are indexed into it.
    Unspecified `qdrant` and `zammad` fields are inherited from the root
    configuration; `laws` are defined per target.
    """

    name: str = Field(description="Unique target name used for logging and validation.")
    qdrant: dict[str, Any] = Field(
        description="Qdrant setting overrides for this target, e.g. collection_name.",
        default_factory=dict,
    )
    zammad: dict[str, Any] = Field(
        description="Zammad setting overrides for this target, e.g. knowledge_base_id and category_ids.",
        default_factory=dict,
    )
    laws: list[LawConfig] = Field(
        description="Law sources to ingest into this target's collection.",
        default_factory=list,
    )

    @model_validator(mode="after")
    def _validate_unique_law_ids(self) -> "IndexTargetSettings":
        """Ensure no duplicate law IDs are configured for this target."""
        ids = [law.id for law in self.laws]
        duplicates = sorted({law_id for law_id in ids if ids.count(law_id) > 1})
        if duplicates:
            raise ValueError(f"Duplicate law ids in target '{self.name}': {', '.join(duplicates)}")
        return self
