"""Tests for DLF retrieval guardrail behavior."""

from typing import cast

import httpx
import pytest
from pydantic import HttpUrl

from app.answer.dlf import DLFClient
from app.errors import DLFError
from app.guardrails import GuardrailService
from app.settings.answer import DLFSettings
from app.settings.guardrails import GuardrailSettings


class _GuardrailStub:
    def __init__(self, settings: GuardrailSettings, result: bool) -> None:
        self.settings = settings
        self._result = result

    async def evaluate(self, *args, **kwargs) -> bool:
        del args, kwargs
        return self._result


@pytest.mark.asyncio
async def test_retrieve_documents_allows_queries_when_guardrails_disabled() -> None:
    """DLF should retrieve documents even if the guardrail result is false when guardrails are disabled."""
    guardrail_service = _GuardrailStub(GuardrailSettings(enabled=False), result=False)
    service = DLFClient(
        DLFSettings(url=HttpUrl("http://testserver"), filter_categories=[]),
        cast(GuardrailService, guardrail_service),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/retrieval"
        return httpx.Response(
            200,
            json={
                "retrieval_documents": [
                    {
                        "name": "  Example  ",
                        "page_content": "Line 1\nLine 2  ",
                        "metadata": {"source": "https://example.test/doc"},
                    }
                ]
            },
        )

    await service.client.aclose()
    service.__dict__["client"] = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://testserver",
        timeout=2.0,
    )

    try:
        documents = await service.retrieve_documents("unsafe query")

        assert len(documents) == 1
        assert documents[0].title == "Example"
        assert documents[0].content == "Line 1 Line 2"
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_retrieve_documents_blocks_unsafe_query_when_guardrails_enabled() -> None:
    """DLF should raise a permanent error only for unsafe queries when guardrails are enabled."""
    guardrail_service = _GuardrailStub(GuardrailSettings(enabled=True), result=False)
    service = DLFClient(
        DLFSettings(url=HttpUrl("http://testserver"), filter_categories=[]),
        cast(GuardrailService, guardrail_service),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"Unexpected request to {request.url}")

    await service.client.aclose()
    service.__dict__["client"] = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://testserver",
        timeout=2.0,
    )

    try:
        with pytest.raises(DLFError, match="Query flagged as unsafe by guardrails"):
            await service.retrieve_documents("unsafe query")
    finally:
        await service.close()
