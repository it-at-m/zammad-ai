"""Request and response models for the public v1 API."""

from pydantic import BaseModel, Field

from .answer import DocumentDict
from .triage import TriageResult


class TriageInput(BaseModel):
    """Payload for a triage request."""

    text: str
    session_id: str | None = None


class TriageOutput(BaseModel):
    """Response payload for a triage request."""

    triage: TriageResult
    session_id: str


class AnswerInput(BaseModel):
    """Payload for an answer request."""

    text: str
    session_id: str | None = None
    ticket_id: int | None = None
    category: str
    action: str


class AnswerOutput(BaseModel):
    """Response payload for an answer request."""

    response: str = Field(description="The final answer to the user's question.")
    documents: list[DocumentDict] = Field(description="List of documents supporting the answer.")


class HealthCheckResponse(BaseModel):
    """Health check response returned by the backend."""

    status: str = Field(
        description="Health status of the API. Expected value is 'healthy' when the API is operational.",
        default="healthy",
    )
