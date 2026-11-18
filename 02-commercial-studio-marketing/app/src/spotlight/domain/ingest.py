"""Document text extraction for Brand Brain ingestion (md / txt / pdf / docx)."""

from __future__ import annotations

import io

from ..errors import AppError, ValidationFailed

MAX_PDF_PAGES = 80
TEXT_EXT = {".md", ".markdown", ".txt", ".csv", ".json", ".rtf"}


def extract_text(filename: str, data: bytes) -> str:
    name = filename.lower()
    if any(name.endswith(e) for e in TEXT_EXT):
        return data.decode("utf-8", errors="replace")
    if name.endswith(".pdf"):
        from pypdf import PdfReader

        try:
            reader = PdfReader(io.BytesIO(data))
            return "\n\n".join((p.extract_text() or "") for p in reader.pages[:MAX_PDF_PAGES])
        except Exception as exc:
            raise ValidationFailed(f"could not read PDF: {type(exc).__name__}", code="bad_document", key="err.bad_document.pdf", params={"detail": type(exc).__name__}) from exc
    if name.endswith(".docx"):
        from docx import Document

        try:
            doc = Document(io.BytesIO(data))
        except Exception as exc:
            raise ValidationFailed(f"could not read DOCX: {type(exc).__name__}", code="bad_document", key="err.bad_document.docx", params={"detail": type(exc).__name__}) from exc
        parts = [p.text for p in doc.paragraphs if p.text.strip()]
        for t in doc.tables:
            for row in t.rows:
                parts.append(" | ".join(c.text.strip() for c in row.cells))
        return "\n\n".join(parts)
    raise AppError("unsupported file type (use .md, .txt, .pdf or .docx)", code="unsupported_media", status=415, key="err.unsupported_media.doc")
