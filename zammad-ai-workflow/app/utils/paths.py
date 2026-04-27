"""Utilities for resolving package-relative paths."""

from pathlib import Path


def get_prompts_dir() -> Path:
    """Resolve the absolute path to the package's prompts directory.

    The path is determined relative to this module's location by ascending to the package root and appending "prompts".

    Returns:
        Path: The absolute path to the prompts directory.
    """
    return Path(__file__).resolve().parents[2] / "prompts"
