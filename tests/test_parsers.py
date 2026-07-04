"""Parser unit tests (M3) — no DB, runs under ``make test``.

Parsers return a LIST of page segments (``list[ParseResult]``); PDF yields one per page, text /
markdown / docx yield a single segment.
"""

from __future__ import annotations

import io

import pytest

from app.infra.parsers import UnsupportedFormat, get_parser
from app.infra.parsers.docx import DocxParser
from app.infra.parsers.pdf import PdfParser
from app.infra.parsers.text import TextParser


def test_paste_returns_text_parser_and_decodes_utf8():
    parser = get_parser("paste")
    assert isinstance(parser, TextParser)
    segments = parser.parse("héllo wörld".encode("utf-8"))
    assert len(segments) == 1
    assert segments[0].text == "héllo wörld"
    assert segments[0].page_number is None


def test_invalid_utf8_is_replaced_not_raised():
    segments = get_parser("paste").parse(b"ok \xff done")
    assert "ok " in segments[0].text and "done" in segments[0].text  # no exception


@pytest.mark.parametrize(
    "filename,content_type",
    [
        ("policy.txt", "text/plain"),
        ("readme.md", "text/markdown"),
        ("notes.MD", None),
        ("x", "text/plain; charset=utf-8"),
    ],
)
def test_text_and_markdown_files_use_text_parser(filename, content_type):
    assert isinstance(get_parser("file", filename, content_type), TextParser)


def test_pdf_and_docx_route_to_their_parsers():
    assert isinstance(get_parser("file", "scan.pdf", "application/pdf"), PdfParser)
    assert isinstance(get_parser("file", "doc.docx", None), DocxParser)


@pytest.mark.parametrize(
    "filename,content_type",
    [("data.bin", "application/octet-stream"), ("sheet.xlsx", None), ("img.png", "image/png")],
)
def test_unsupported_file_types_raise(filename, content_type):
    with pytest.raises(UnsupportedFormat):
        get_parser("file", filename, content_type)


def test_url_kind_does_not_reach_get_parser():
    # URL sources are crawled (text pre-extracted), so get_parser("url") is unsupported.
    with pytest.raises(UnsupportedFormat):
        get_parser("url", None, None)


def _make_docx(text: str) -> bytes:
    from docx import Document

    document = Document()
    for line in text.split("\n"):
        document.add_paragraph(line)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def test_docx_parser_extracts_paragraph_text():
    data = _make_docx("Return policy\n30 days for a full refund")
    segments = get_parser("file", "policy.docx", None).parse(data)
    assert len(segments) == 1
    assert "Return policy" in segments[0].text
    assert "refund" in segments[0].text


def test_pdf_parser_rejects_non_pdf_bytes():
    with pytest.raises(UnsupportedFormat):
        get_parser("file", "x.pdf", "application/pdf").parse(b"this is not a pdf")
