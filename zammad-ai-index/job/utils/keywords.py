"""Keyword generation helpers for indexed content."""

from functools import lru_cache
from typing import Any

from pydantic import BaseModel, Field

from job.settings.settings import ZammadAIIndexSettings, get_settings
from job.utils.logging import getLogger

logger = getLogger("zammad-ai-index.keywords")
settings: ZammadAIIndexSettings = get_settings()


class KeywordGenerationResult(BaseModel):
    """Structured response for generated index keywords."""

    keywords: list[str] = Field(
        description="Exactly five very short keywords extracted from the body text.",
        min_length=5,
        max_length=5,
    )


@lru_cache(maxsize=1)
def _get_keyword_chat_model() -> Any:
    """Create the chat model used for keyword extraction."""
    match settings.genai.sdk:
        case "openai":
            from langchain_openai import ChatOpenAI

            return ChatOpenAI(
                model=settings.genai.chat_model,
                temperature=settings.genai.temperature,
                max_retries=settings.genai.max_retries,
            )
        case _:
            logger.error(f"Unsupported GenAI SDK '{settings.genai.sdk}' for keyword generation")
            raise ValueError("Unsupported GenAI SDK for keyword generation")


def generate_keywords(body_text: str) -> list[str]:
    """Generate five concise keywords from the provided body text."""
    if not body_text.strip():
        return []

    keyword_model = _get_keyword_chat_model().with_structured_output(KeywordGenerationResult)
    result = keyword_model.invoke(
        [
            (
                "system",
                "Generate exactly five very short keywords for search indexing. "
                "Use the same language as the provided body text and only concepts present in it. "
                "Prefer single words. Use short two-word terms only when the combination has a specific meaning.",
            ),
            (
                "human",
                "Body text:\n\n"
                f"{body_text}\n\n"
                "Return exactly five keywords. Keep each keyword very short. "
                "Avoid long phrases, full sentences, numbering, and explanations.",
            ),
        ]
    )

    if isinstance(result, KeywordGenerationResult):
        keywords = result.keywords
    else:
        keywords = KeywordGenerationResult.model_validate(result).keywords

    normalized_keywords: list[str] = []
    for keyword in keywords:
        normalized_keyword = " ".join(keyword.strip().split())
        if normalized_keyword and normalized_keyword not in normalized_keywords:
            normalized_keywords.append(normalized_keyword)

    if len(normalized_keywords) != 5:
        raise ValueError("Keyword generation did not produce five unique keywords")

    return normalized_keywords


def format_keywords_content(keywords: list[str]) -> str:
    """Format generated keywords for inclusion in indexed content."""
    if not keywords:
        return ""
    return f"Keywords: {', '.join(keywords)}"
