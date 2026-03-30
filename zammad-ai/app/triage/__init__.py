"""Triage service package for Zammad AI."""

from .triage import TriageService, get_triage_service

__all__: list[str] = [
    "get_triage_service",
    "TriageService",
]
