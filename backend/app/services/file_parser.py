"""
File parser service — extracts plain text from uploaded files.

Supported formats:
  .txt  — read as-is
  .md   — read as-is (markdown treated as plain text for chunking)
  .pdf  — extract text via PyMuPDF (fitz)
  .docx — extract text via python-docx
"""
from __future__ import annotations

import io
import logging
from pathlib import PurePath

logger = logging.getLogger(__name__)

# Allowed extensions and their MIME types
ALLOWED_EXTENSIONS: dict[str, list[str]] = {
    ".txt": ["text/plain"],
    ".md": ["text/markdown", "text/plain"],
    ".pdf": ["application/pdf"],
    ".docx": [
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ],
}

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB


def allowed_extension(filename: str) -> bool:
    """Check if the file extension is in the allow-list."""
    suffix = PurePath(filename).suffix.lower()
    return suffix in ALLOWED_EXTENSIONS


def parse_file(filename: str, content: bytes) -> str:
    """
    Extract plain text from a file's binary content.

    Raises ValueError for unsupported formats or empty content.
    """
    suffix = PurePath(filename).suffix.lower()

    if suffix in {".txt", ".md"}:
        return _parse_text(content)
    if suffix == ".pdf":
        return _parse_pdf(content)
    if suffix == ".docx":
        return _parse_docx(content)

    raise ValueError(f"Unsupported file type: {suffix}")


def _parse_text(content: bytes) -> str:
    """Decode plain text / markdown."""
    text = content.decode("utf-8", errors="replace").strip()
    if not text:
        raise ValueError("File is empty")
    return text


def _parse_pdf(content: bytes) -> str:
    """Extract text from a PDF using PyMuPDF."""
    try:
        import fitz  # PyMuPDF
    except ImportError:
        raise ValueError(
            "PDF support requires PyMuPDF. Install with: pip install pymupdf"
        )

    doc = fitz.open(stream=content, filetype="pdf")
    pages_text: list[str] = []
    for page in doc:
        pages_text.append(page.get_text())
    doc.close()

    text = "\n\n".join(pages_text).strip()
    if not text:
        raise ValueError("Could not extract text from PDF (may be scanned/image-based)")
    return text


def _parse_docx(content: bytes) -> str:
    """Extract text from a DOCX using python-docx."""
    try:
        from docx import Document
    except ImportError:
        raise ValueError(
            "DOCX support requires python-docx. Install with: pip install python-docx"
        )

    doc = Document(io.BytesIO(content))
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    text = "\n\n".join(paragraphs).strip()
    if not text:
        raise ValueError("DOCX file has no extractable text")
    return text
