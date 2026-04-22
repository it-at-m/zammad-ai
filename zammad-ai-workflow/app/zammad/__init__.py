"""Zammad API client implementations for ticket management and knowledge base access."""

from .api import ZammadAPIClient
from .base import BaseZammadClient, ZammadConnectionError
from .eai import ZammadEAIClient

__all__ = [
    "BaseZammadClient",
    "ZammadAPIClient",
    "ZammadConnectionError",
    "ZammadEAIClient",
]
