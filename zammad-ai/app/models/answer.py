from pydantic import BaseModel, Field


class DocumentDict(BaseModel):
    title: str = Field(description="The title of the document.")
    url: str = Field(description="The URL source of the document.")


class StructuredAgentResponse(BaseModel):
    response: str = Field(description="The final answer to the user's question.")
    documents: list[DocumentDict] = Field(description="List of documents supporting the answer.")
    auto_publish: bool = Field(description="Whether the answer should be automatically published based on the judge's evaluation.")


class JudgeResult(BaseModel):
    context_relevance: float = Field(description="The relevance of the context to the question.", ge=0.0, le=1.0)
    groundedness: float = Field(description="The extent to which the answer is grounded in the provided context.", ge=0.0, le=1.0)
    answer_relevance: float = Field(description="The relevance of the answer to the question.", ge=0.0, le=1.0)
    passed: bool = Field(description="Whether the answer passed the judge criteria.")
    reasoning: str = Field(description="The reasoning behind the judge's decision.")
    repair_instructions: str | None = Field(description="Instructions for repairing the answer, if applicable.", default=None)
