"""Hashing and normalization helpers for indexing content."""

from hashlib import sha256
from re import sub


def hash_content(content: str) -> str:
    """Hash the given content string using a simple hash function."""
    return sha256(content.encode("utf-8")).hexdigest()


def normalize_content(content: str) -> str:
    """Normalize the given content string by stripping whitespace, collapsing multiple spaces and lowercasing."""
    return sub(r"\s+", " ", content.strip()).lower()
