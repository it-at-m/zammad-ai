from pydantic import BaseModel, Field

from .answer import DocumentDict
from .triage import TriageResult


class TriageInput(BaseModel):
    text: str
    session_id: str | None = None


class TriageOutput(BaseModel):
    triage: TriageResult
    session_id: str


class AnswerInput(BaseModel):
    text: str
    session_id: str | None = None
    ticket_id: int | None = None
    category: str
    action: str


class AnswerOutput(BaseModel):
    response: str = Field(description="The final answer to the user's question.")
    documents: list[DocumentDict] = Field(description="List of documents supporting the answer.")


class HealthCheckResponse(BaseModel):
    status: str = Field(
        description="Health status of the API. Expected value is 'healthy' when the API is operational.",
        default="healthy",
    )
