"""Test configuration for slm-guardrails.

Ensures the package path is importable when running tests from the repository root.
"""

import sys
from pathlib import Path

# Prepend slm-guardrails project root to sys.path so `guardrail_app` can be imported
SLM_ROOT = Path(__file__).resolve().parents[1]
if str(SLM_ROOT) not in sys.path:
    sys.path.append(str(SLM_ROOT))
