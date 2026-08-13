"""Test configuration for slm-guardrails.

Ensures the package path is importable when running tests from the repository root.
"""

import sys
from collections.abc import Generator
from pathlib import Path

import pytest

# Prepend slm-guardrails project root to sys.path so `guardrail_app` can be imported
SLM_ROOT = Path(__file__).resolve().parents[1]
if str(SLM_ROOT) not in sys.path:
    sys.path.append(str(SLM_ROOT))


@pytest.fixture(autouse=True)
def cleanup_log_config_cache() -> Generator[None, None, None]:
    """Reset cached logging configuration before and after each test."""
    from guardrail_app.utils.logging import reset_logging_state

    reset_logging_state()
    yield
    reset_logging_state()
