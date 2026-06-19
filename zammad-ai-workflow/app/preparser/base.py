"""Abstract base class for preparsers.

This module defines the minimal contract implementers must follow.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class AbstractPreparser(ABC):
    """Abstract preparser interface.

    Implementers should provide a `parse(message: str) -> str` method which
    returns either a transformed message or the original message when no
    transformation is applicable.

    Implementations MUST avoid raising on malformed input; the service layer
    will catch exceptions and fall back to the original message. Keeping the
    base class minimal avoids coupling.
    """

    @abstractmethod
    def parse(self, message: str) -> str:
        """Parse and possibly transform a message.

        Parameters:
            message: Raw input text to parse.

        Returns:
            The transformed text, or the original message if no changes are made.
        """
        raise NotImplementedError
