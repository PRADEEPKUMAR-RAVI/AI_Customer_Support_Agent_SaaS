"""PDF parser — one ParseResult per page (page_number set for file citations, [A13])."""

from __future__ import annotations

import io

from app.infra.parsers.base import ParseResult, UnsupportedFormat

PDF_EXTENSIONS = {".pdf"}
PDF_CONTENT_TYPES = {"application/pdf"}


class PdfParser:
    def parse(self, data: bytes) -> list[ParseResult]:
        from pypdf import PdfReader  # lazy — heavy import

        try:
            reader = PdfReader(io.BytesIO(data))
        except Exception as exc:  # noqa: BLE001 — corrupt/encrypted PDF -> terminal failure
            raise UnsupportedFormat(f"could not read PDF: {exc}") from exc

        segments: list[ParseResult] = []
        for i, page in enumerate(reader.pages, start=1):
            text = (page.extract_text() or "").strip()
            if text:
                segments.append(ParseResult(text=text, page_number=i))
        if not segments:
            raise UnsupportedFormat("PDF has no extractable text (scanned/image-only)")
        return segments


def can_parse_pdf(filename: str | None, content_type: str | None) -> bool:
    ext = ("." + filename.rsplit(".", 1)[-1].lower()) if filename and "." in filename else ""
    ct = (content_type or "").split(";", 1)[0].strip().lower()
    return ext in PDF_EXTENSIONS or ct in PDF_CONTENT_TYPES
