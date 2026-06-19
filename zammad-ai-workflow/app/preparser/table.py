"""Concrete preparser that extracts values from Markdown tables.

The parser is intentionally lightweight: it finds Markdown-style tables using
the separator row (---) and extracts rows whose first cell matches one of the
configured `keep_rows`.

Limitations: this is not a full Markdown parser. Pipes inside code spans or
other complex table constructs may be parsed incorrectly. For robustness the
parser fails open and returns the original message on unexpected errors.
"""

from __future__ import annotations

import re
from typing import Iterable

from app.preparser.base import AbstractPreparser
from app.utils.logging import getLogger

logger = getLogger("zammad-ai.preparser.table")


class TablePreparser(AbstractPreparser):
    """Extract configured rows from Markdown tables."""

    _separator_re = re.compile(r"^\s*\|?(?:\s*:?-+:?\s*\|)+\s*$")

    def __init__(self, keep_rows: list[str], case_sensitive: bool = False, value_column: int = 1) -> None:
        """Create a TablePreparser object.

        Args:
            keep_rows: List of row title strings to match against the first cell.
            case_sensitive: Whether matching is case-sensitive (default: False).
            value_column: Index of column to treat as the value (default: 1 -> second column).
        """
        self.case_sensitive = case_sensitive
        self.value_column = int(value_column)
        # Normalize configured titles for matching
        if case_sensitive:
            self._norm_map = {t.strip(): t for t in keep_rows}
        else:
            self._norm_map = {t.strip().lower(): t for t in keep_rows}

    def _normalize(self, s: str) -> str:
        s = s.strip()
        return s if self.case_sensitive else s.lower()

    def _iter_tables(self, lines: list[str]) -> Iterable[tuple[int, int]]:
        """Yield (start, end) line indexes for table body rows (exclusive end).

        A table is detected by a header line followed by a separator matching
        `_separator_re`. Table rows continue while lines contain a pipe (`|`).
        """
        for i, line in enumerate(lines):
            if self._separator_re.match(line):
                # start collecting rows after the separator
                j = i + 1
                while j < len(lines) and ("|" in lines[j] and lines[j].strip() != ""):
                    j += 1
                yield (i + 1, j)

    def parse(self, message: str) -> str:
        """Parse a provided message according to configuration.

        Args:
            message (str): Incoming user message.

        Returns:
            str: Parsed user message.
        """
        try:
            if not message or "|" not in message:
                return message

            lines = message.splitlines()
            sections: list[str] = []

            for start, end in self._iter_tables(lines):
                for idx in range(start, end):
                    row = lines[idx]
                    # split on pipes, ignore leading/trailing empties caused by outer pipes
                    cells = [c.strip() for c in row.split("|")]
                    # remove empty leading/trailing cells
                    if cells and cells[0] == "":
                        cells = cells[1:]
                    if cells and cells[-1] == "":
                        cells = cells[:-1]

                    if not cells:
                        continue

                    first = cells[0]
                    norm = self._normalize(first)
                    if norm in self._norm_map:
                        title = self._norm_map[norm]
                        # get value column if present
                        value = ""
                        if len(cells) > self.value_column:
                            # join remaining columns if any beyond the value column
                            extra = " | ".join(cells[self.value_column :])
                            value = extra.strip()
                        elif len(cells) > 1:
                            value = cells[self.value_column].strip() if self.value_column < len(cells) else ""

                        sections.append(f"## {title}\n{value}")

            if sections:
                result = "\n\n".join(sections)
                logger.info("Preparser extracted %d table rows", len(sections))
                return result

            return message
        except Exception:
            logger.error("TablePreparser failed; returning original message.", exc_info=True)
            return message
