r"""Parse prompt files with optional YAML frontmatter."""

from logging import Logger
from pathlib import Path
from typing import Any

from yaml import safe_load

from app.utils.logging import getLogger

logger: Logger = getLogger("zammad-ai.utils.prompts")


def extract_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    r"""Extract YAML frontmatter and remaining content from markdown text.

    Frontmatter must be delimited by `---` at the start of the file.
    If no frontmatter is present, returns empty dict and the full content.

    Args:
        content: The full content string (potentially with frontmatter)

    Returns:
        Tuple of (frontmatter_dict, remaining_prompt_text).
        If no frontmatter found, frontmatter_dict will be empty.

    Examples:
        >>> text = "---\\nversion: 1\\n---\\nPrompt content"
        >>> metadata, prompt = extract_frontmatter(text)
        >>> metadata
        {'version': 1}
        >>> prompt
        'Prompt content'

        >>> text = "Just prompt text"
        >>> metadata, prompt = extract_frontmatter(text)
        >>> metadata
        {}
        >>> prompt
        'Just prompt text'
    """
    content = content.lstrip()

    # Check if content starts with frontmatter delimiter
    if not content.startswith("---"):
        return {}, content

    # Find the end of frontmatter (second `---`)
    remaining: str = content[3:].lstrip("\n")
    lines: list[str] = remaining.split("\n")

    end_index: int | None = None
    for i, line in enumerate(lines):
        if line.strip() == "---":
            end_index = i
            break

    if end_index is None:
        # No closing delimiter found, treat entire content as prompt
        return {}, content

    # Extract frontmatter and remaining content
    frontmatter_text: str = "\n".join(lines[:end_index]).strip()
    prompt_text: str = "\n".join(lines[end_index + 1 :]).lstrip("\n")

    # Parse YAML frontmatter
    metadata: dict[str, Any] = {}
    if frontmatter_text:
        try:
            metadata = safe_load(frontmatter_text) or {}
        except Exception:
            logger.warning("Failed to parse YAML frontmatter.", exc_info=True)

    return metadata, prompt_text


def load_prompt(file_path: Path | str) -> str:
    """Load a prompt file and remove any leading YAML frontmatter.

    Parameters:
        file_path (Path | str): Path to the prompt file; may be a string or Path.

    Returns:
        The prompt text excluding any YAML frontmatter, with leading and trailing whitespace removed.

    Raises:
        FileNotFoundError: If the file does not exist.
    """
    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")

    content: str = path.read_text(encoding="utf-8")
    _, prompt_text = extract_frontmatter(content)

    return prompt_text.strip()
