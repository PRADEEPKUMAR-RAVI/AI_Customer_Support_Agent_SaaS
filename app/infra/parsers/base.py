"""Parser seam — bytes -> extracted text (M3, Phase 1).

A parser turns a source's raw bytes into plain text for chunking. Phase 1 ships only the text
parser (paste / .txt / .md); PDF and DOCX parsers slot in behind this same protocol in Phase 2.
``page_number`` exists on the result so a future PDF parser can carry per-chunk pagination for
citations ([A13]); the text parser always leaves it ``None``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass
class ParseResult:
    """One text segment. ``page_number`` is set by paginated parsers (PDF) for file citations
    ([A13]); ``source_url`` is set by the URL crawler for the specific crawled page."""

    text: str
    page_number: int | None = None
    source_url: str | None = None


class UnsupportedFormat(Exception):
    """Raised when no parser handles the given source kind / file type.

    The API maps this to a 415; the ingest worker maps it to a terminal ``failed`` source.
    """

    def __init__(self, detail: str = "") -> None:
        super().__init__(detail)
        self.detail = detail


@runtime_checkable
class Parser(Protocol):
    def parse(self, data: bytes) -> list[ParseResult]: ...
