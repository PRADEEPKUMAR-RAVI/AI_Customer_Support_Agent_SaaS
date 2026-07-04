"""Parser registry — selects a ``Parser`` for a source (M3).

Phase 1 handles ``kind="paste"`` and text/markdown files. ``kind="url"`` (crawler) and
PDF/DOCX files are Phase 2 — they raise ``UnsupportedFormat`` here until their parsers land.
"""

from __future__ import annotations

from app.infra.parsers.base import ParseResult, Parser, UnsupportedFormat
from app.infra.parsers.docx import DocxParser, can_parse_docx
from app.infra.parsers.pdf import PdfParser, can_parse_pdf
from app.infra.parsers.text import TextParser, can_parse_file

__all__ = ["ParseResult", "Parser", "UnsupportedFormat", "get_parser"]


def get_parser(
    kind: str, filename: str | None = None, content_type: str | None = None
) -> Parser:
    """Return the parser for a source, or raise ``UnsupportedFormat``.

    - ``paste`` -> plain text.
    - ``file``  -> text/markdown, PDF, or DOCX; else unsupported.
    - ``url``   -> the crawler feeds pre-extracted text through the text parser at ingest time,
      so a URL source never reaches ``get_parser`` for parsing.
    """
    if kind == "paste":
        return TextParser()
    if kind == "file":
        if can_parse_file(filename, content_type):
            return TextParser()
        if can_parse_pdf(filename, content_type):
            return PdfParser()
        if can_parse_docx(filename, content_type):
            return DocxParser()
        raise UnsupportedFormat(
            f"unsupported file type (.txt/.md/.pdf/.docx only): "
            f"filename={filename!r} content_type={content_type!r}"
        )
    raise UnsupportedFormat(f"unsupported source kind: {kind!r}")
