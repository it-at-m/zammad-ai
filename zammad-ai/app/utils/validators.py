"""Validation helpers for prompt and configuration files."""

from pathlib import Path


def validate_is_prompt(path: Path) -> Path:
    """Validate that the given file path represents a prompt file with a .txt or .md suffix.

    Parameters:
        path (Path): File system path to validate.

    Returns:
        Path: The original `path` when its suffix is `.txt` or `.md`.

    Raises:
        ValueError: If the path's suffix is not `.txt` or `.md`.
    """
    if path.suffix.lower() not in [".txt", ".md"]:
        raise ValueError("Only TXT and MD files are allowed")
    return path
