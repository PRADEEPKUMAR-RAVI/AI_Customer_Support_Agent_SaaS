"""Plain-text parser — paste, .txt, .md (M3, Phase 1).

Decodes bytes as UTF-8 with ``errors="replace"`` so an odd byte can never crash ingestion; the
replacement char is rare and harmless for retrieval. Markdown is treated as plain text (no
structure parsing in Phase 1).
"""

from __future__ import annotations

import os

from app.infra.parsers.base import ParseResult

TEXT_EXTENSIONS = {".txt", ".md", ".markdown"}
TEXT_CONTENT_TYPES = {"text/plain", "text/markdown", "text/x-markdown"}


class TextParser:
    def parse(self, data: bytes) -> list[ParseResult]:
        return [ParseResult(text=data.decode("utf-8", errors="replace"))]


def can_parse_file(filename: str | None, content_type: str | None) -> bool:
    """True if a filename extension or content-type marks this as plain text / markdown."""
    ext = os.path.splitext(filename or "")[1].lower()
    ct = (content_type or "").split(";", 1)[0].strip().lower()
    return ext in TEXT_EXTENSIONS or ct in TEXT_CONTENT_TYPES
