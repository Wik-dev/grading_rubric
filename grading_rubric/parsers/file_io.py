"""Generic file readers shared by `ingest` and `parse_inputs`.

DR-IO scope: PDF / DOCX / TXT / Markdown text extraction; OCR for handwritten
PDFs is **not** part of this module — it goes through the gateway via the
`StudentCopyReader` interface (DR-ARC-05). Here we cover the deterministic
extraction path; if a file has no extractable text the caller decides what
to do (the parsers stage applies the role-aware no-text-PDF policy).
"""

from __future__ import annotations

from pathlib import Path


def read_text_file(path: Path) -> str:
    """Read a UTF-8 text file. Raises if the file is not decodable as UTF-8."""

    return path.read_text(encoding="utf-8")


def read_pdf_text(path: Path) -> str:
    """Extract text from a PDF using pdfplumber, falling back to pypdf.

    Returns an empty string when neither library can extract text — the
    caller (the parsers stage) then decides whether to route the file to OCR
    via the `StudentCopyReader` (DR-IO-03 image gate).
    """

    try:
        import pdfplumber  # noqa: PLC0415
    except ImportError:
        pdfplumber = None  # type: ignore[assignment]

    if pdfplumber is not None:
        try:
            with pdfplumber.open(str(path)) as pdf:
                pages = [p.extract_text() or "" for p in pdf.pages]
            text = "\n\n".join(pages).strip()
            if text:
                return text
        except Exception:  # noqa: BLE001 — defensively fall back to pypdf
            pass

    try:
        from pypdf import PdfReader  # noqa: PLC0415
    except ImportError:
        return ""

    try:
        reader = PdfReader(str(path))
        pages = [p.extract_text() or "" for p in reader.pages]
        return "\n\n".join(pages).strip()
    except Exception:  # noqa: BLE001
        return ""


def read_docx_text(path: Path) -> str:
    try:
        import docx  # noqa: PLC0415
    except ImportError:
        return ""
    try:
        d = docx.Document(str(path))
        return "\n".join(p.text for p in d.paragraphs).strip()
    except Exception:  # noqa: BLE001
        return ""


def read_any_text(path: Path) -> str:
    """Dispatch to the right reader based on extension."""

    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return read_pdf_text(path)
    if suffix in {".docx"}:
        return read_docx_text(path)
    if suffix in {".txt", ".md", ".markdown", ".rst", ".json"}:
        return read_text_file(path)
    # Unknown extension — try as text, swallow errors.
    try:
        return read_text_file(path)
    except (UnicodeDecodeError, OSError):
        return ""
