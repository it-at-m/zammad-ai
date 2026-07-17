"""API response and agent output models for the answer workflow."""

from pydantic import BaseModel, Field


class DocumentDict(BaseModel):
    """Reference document included with an answer response."""

    title: str = Field(description="The title of the document.")
    url: str = Field(description="The URL source of the document.")


class AnswerCandidate(BaseModel):
    """Answer candidate returned by the answer agent."""

    subject: str | None = Field(
        description="The subject line for the answer. Min length 50 chars, max length 200 chars.",
        min_length=50,
        max_length=200,
    )
    response: str = Field(
        description="The final answer to the user's question. Min length 200 chars.",
        min_length=200,
    )
    documents: list[DocumentDict] = Field(description="List of documents supporting the answer.")
    auto_publish: bool = Field(
        default=True,
        description="Whether the answer should be automatically published based on the judge's evaluation.",
    )


class NoAnswerPossible(BaseModel):
    """Information that no answer can be given based on the available info or rules."""

    reasoning: str = Field(
        description="The reasoning to why no answer can be given. Min length 100 chars, max length 500 chars.",
        min_length=100,
        max_length=500,
    )


class StaticAnswer(BaseModel):
    """Static Answer configured by admin."""

    response: str = Field(
        description="Predefined static response configured by admin to ensure accurate and consistent response."
    )


class JudgeResult(BaseModel):
    """Evaluation results from the answer judge."""

    context_relevance: float = Field(description="The relevance of the context to the question.", ge=0.0, le=1.0)
    groundedness: float = Field(
        description="The extent to which the answer is grounded in the provided context.", ge=0.0, le=1.0
    )
    answer_relevance: float = Field(description="The relevance of the answer to the question.", ge=0.0, le=1.0)
    passed: bool = Field(description="Whether the answer passed the judge criteria.")
    reasoning: str = Field(description="The reasoning behind the judge's decision.")
    repair_instructions: str | None = Field(
        description="Instructions for repairing the answer, if applicable.", default=None
    )
