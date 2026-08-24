"""Helper functions for multi-query retrieval."""

import json

from langchain_classic.retrievers.multi_query import MultiQueryRetriever
from langchain_core.callbacks import AsyncCallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.prompts import PromptTemplate
from langchain_qdrant import QdrantVectorStore
from qdrant_client.models import Filter

from app.settings import MultiQuerySettings
from app.utils.logging import getLogger

logger = getLogger("zammad-ai.answer.multiquery_helper")

MULTI_QUERY_PROMPT = PromptTemplate.from_template(
    """You are an assistant for searching in a vector database.
Generate 3 short, completely different phrased search queries in the input language.
The queries should be semantically similar to the original question, but with totally different wording and phrasing to increase the chance of finding relevant documents.
Respond with only one search query per line and without additional explanations.
Original question: {question}"""
)


def _document_key(document: Document) -> str:
    return json.dumps(
        {
            "id": document.metadata.get("id", ""),
            "page_content": document.page_content,
            "metadata": document.metadata,
        },
        sort_keys=True,
        default=str,
    )


def _deduplicate_queries(queries: list[str]) -> list[str]:
    seen: set[str] = set()
    unique_queries: list[str] = []
    for query in queries:
        normalized = query.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        unique_queries.append(normalized)
    return unique_queries


async def _build_queries(
    query: str,
    multi_query_retriever: MultiQueryRetriever | None,
    multi_query_settings: MultiQuerySettings | None,
) -> list[str]:
    if multi_query_retriever is None or multi_query_settings is None or not multi_query_settings.enabled:
        return [query]

    try:
        run_manager = AsyncCallbackManagerForRetrieverRun.get_noop_manager()
        queries: list[str] = await multi_query_retriever.agenerate_queries(query, run_manager)
        if multi_query_settings.include_original:
            queries.append(query)
        return _deduplicate_queries(queries)
    except Exception:
        logger.warning("Falling back to single-query retrieval after multi-query generation failed.", exc_info=True)
        return [query]


async def _search_documents_across_queries(
    vectorstore: QdrantVectorStore,
    retrieval_num_documents: int,
    queries: list[str],
    k: int,
    offset: int,
    search_filter: Filter | None,
) -> list[tuple[Document, float]]:
    best_matches: dict[str, tuple[Document, float, int]] = {}
    per_query_k = max(k + offset, retrieval_num_documents)
    for query_index, current_query in enumerate(queries):
        documents_with_scores = await vectorstore.asimilarity_search_with_relevance_scores(
            query=current_query,
            k=per_query_k,
            offset=0,
            filter=search_filter,
        )
        for document, score in documents_with_scores:
            key = _document_key(document)
            existing = best_matches.get(key)
            if existing is None or score > existing[1] or (score == existing[1] and query_index < existing[2]):
                best_matches[key] = (document, score, query_index)

    ranked_documents = sorted(best_matches.values(), key=lambda item: (-item[1], item[2]))
    sliced_documents = ranked_documents[offset : offset + k]
    return [(document, score) for document, score, _ in sliced_documents]
