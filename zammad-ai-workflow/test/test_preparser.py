"""Unit tests for the preparser package.

These tests validate the Markdown table preparser and the preparser service
behavior (pass-through when disabled and configuration validation).
"""

import pytest

from app.preparser.service import PreparserService
from app.preparser.table import TablePreparser
from app.settings.preparser import PreparserSettings


def test_table_preparser_extracts_matching_rows() -> None:
    """Ensure TablePreparser extracts configured rows and their values from a markdown table."""
    table = (
        "| Field | Value |\n"
        "| --- | --- |\n"
        "| Summary | This is a summary. |\n"
        "| Unrelated | ignore |\n"
        "| Steps to reproduce | Step 1; Step 2 |\n"
    )

    p = TablePreparser(keep_rows=["Summary", "Steps to reproduce"])
    out = p.parse(table)

    assert "## Summary" in out
    assert "This is a summary." in out
    assert "## Steps to reproduce" in out
    assert "Step 1; Step 2" in out


def test_table_preparser_passthrough_when_no_table() -> None:
    """When no table is present, the parser should return the original text unchanged."""
    text = "Just a normal paragraph without a table"
    p = TablePreparser(keep_rows=["Summary"])
    assert p.parse(text) == text


def test_table_preparser_partial_matches() -> None:
    """Only configured rows present in the table should be extracted."""
    table = "| A | B |\n| --- | --- |\n| Foo | 1 |\n| Summary | The summary |\n"
    p = TablePreparser(keep_rows=["Summary"])
    out = p.parse(table)
    assert "## Summary" in out
    assert "The summary" in out


def test_preparser_service_disabled_returns_original() -> None:
    """PreparserService should return the original message when disabled."""
    settings = PreparserSettings(enabled=False, config=None)
    svc = PreparserService(settings=settings)
    assert svc.preparse("input") == "input"


def test_preparser_settings_requires_config_when_enabled() -> None:
    """PreparserSettings must raise ValueError if enabled but no config is provided."""
    with pytest.raises(ValueError):
        PreparserSettings(enabled=True, config=None)
