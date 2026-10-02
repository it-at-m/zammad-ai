"""Tests for shared Zammad client HTTP error handling."""

from __future__ import annotations

import json
import logging

import httpx
import pytest
from pydantic import HttpUrl, SecretStr

from app.errors import ZammadPermanentError
from app.settings.zammad import ZammadAPISettings
from app.zammad.api import ZammadAPIClient


@pytest.mark.asyncio
async def test_permanent_zammad_errors_include_response_body_in_logs(caplog: pytest.LogCaptureFixture) -> None:
    """Permanent Zammad failures should keep the response body in the log record."""
    settings = ZammadAPISettings(
        base_url=HttpUrl("http://testserver"),
        auth_token=SecretStr("token"),
        timeout=5,
        max_retries=0,
    )
    client = ZammadAPIClient(settings)

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            422,
            json={"error": "invalid", "detail": "Missing required field"},
        )

    await client.client.aclose()
    client.client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://testserver",
        timeout=5.0,
    )

    caplog.set_level(logging.ERROR, logger="zammad-ai.base")

    try:
        with pytest.raises(ZammadPermanentError) as excinfo:
            await client._request("POST", "/api/v1/tickets/1", json={"subject": "test"})

        assert excinfo.value.status_code == 422
        assert excinfo.value.response_body is not None
        assert "Missing required field" in excinfo.value.response_body

        record = next(record for record in caplog.records if record.name == "zammad-ai.base")
        assert record.status_code == 422
        assert json.loads(record.response_body)["detail"] == "Missing required field"
    finally:
        await client.close()
