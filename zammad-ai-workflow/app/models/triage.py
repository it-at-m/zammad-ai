"""Pydantic models for triage classification and responses."""

from pydantic import BaseModel, Field

from app.settings.triage import Action, Category


class CategorizationResult(BaseModel):
    """A structured response for a categorization request."""

    category: Category | None = Field(description=("The predicted category for the text."))
    reasoning: str = Field(
        description="A single sentence explaining why the text fits the chosen category. Translate the text in german."
    )
    confidence: float = Field(
        description="Value from 0.0 to 1.0 on how sure / confident you are in your categorisation",
        ge=0.0,
        le=1.0,
    )
    extracted_values: dict[str, str | int | float | bool] | None = Field(
        default=None, description="Any extracted values as specified by the category definition"
    )


class TriageResult(BaseModel):
    """Complete result of the triage process."""

    user_text: str = Field(description="The original user text that was categorized.")
    category: Category = Field(description="The predicted category")
    action: Action = Field(description="The recommended action")
    reasoning: str = Field(description="Explanation for the categorization")
    confidence: float = Field(description="Confidence score (0.0 to 1.0)")
    extracted_values: dict[str, str | int | float | bool] | None = Field(
        default=None, description="Any extracted values as specified by the category definition"
    )


class DaysSinceRequestResponse(BaseModel):
    """Structured response for days-since-request evaluation."""

    days_since_request: int = Field(description="Number of days since the request was made")
    reason: str = Field(description="Reason for the calculation")


class ProcessingIdResponse(BaseModel):
    """Structured response for processing-id extraction."""

    processing_id: str = Field(description="Extracted processing ID from the text")
