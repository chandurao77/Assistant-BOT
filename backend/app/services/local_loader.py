"""
Local document loader — ingest plain .txt, .md, .json, or .doc files
from a local folder directly into Qdrant, no Confluence needed.

Supported formats:
  .txt  / .md   — read as-is (plain text or markdown)
  .json         — expects {"title": "...", "content": "...", "url": "..."} or a list of those
  .doc          — Confluence MIME exports (HTML wrapped in MIME envelope)
  .docx         — Word documents (via python-docx)
"""
from __future__ import annotations
import email
import json
import logging
import quopri
from datetime import datetime, timezone
from pathlib import Path

from app.models.document import ConfluencePage
from app.utils.html_parser import html_to_text

logger = logging.getLogger(__name__)

_SUPPORTED = {".txt", ".md", ".json", ".doc", ".docx"}


def load_local_docs(docs_dir: str | Path) -> list[ConfluencePage]:
    """
    Read all supported files in docs_dir and return them as ConfluencePage objects
    (body_html field will contain plain text — the HTML parser handles both).
    """
    folder = Path(docs_dir)
    if not folder.exists():
        raise FileNotFoundError(f"Docs folder not found: {folder.resolve()}")

    pages: list[ConfluencePage] = []
    files = [f for f in sorted(folder.iterdir()) if f.suffix.lower() in _SUPPORTED]

    if not files:
        logger.warning("No supported files (.txt .md .json) found in %s", folder)
        return pages

    for file in files:
        try:
            loaded = _load_file(file)
            pages.extend(loaded)
            logger.info("Loaded %d page(s) from %s", len(loaded), file.name)
        except Exception as exc:
            logger.warning("Skipping %s — %s", file.name, exc)

    logger.info("Total local docs loaded: %d", len(pages))
    return pages


def _load_file(path: Path) -> list[ConfluencePage]:
    suffix = path.suffix.lower()

    if suffix in {".txt", ".md"}:
        content = path.read_text(encoding="utf-8").strip()
        if not content:
            return []
        return [_make_page(
            page_id=f"local_{path.stem}",
            title=_title_from_content(content) or path.stem.replace("_", " ").title(),
            content=content,
            url=path.resolve().as_uri(),
            space_key="LOCAL",
            space_name="Local Documents",
        )]

    if suffix == ".doc":
        return _load_doc(path)

    if suffix == ".docx":
        return _load_docx(path)

    if suffix == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data = [data]
        pages = []
        for i, item in enumerate(data):
            content = item.get("content") or item.get("body") or item.get("text", "")
            if not content:
                continue
            pages.append(_make_page(
                page_id=item.get("id") or f"local_{path.stem}_{i}",
                title=item.get("title", path.stem.replace("_", " ").title()),
                content=content,
                url=item.get("url", path.resolve().as_uri()),
                space_key=item.get("space_key", "LOCAL"),
                space_name=item.get("space_name", "Local Documents"),
            ))
        return pages

    return []


def _make_page(
    page_id: str,
    title: str,
    content: str,
    url: str,
    space_key: str,
    space_name: str,
) -> ConfluencePage:
    return ConfluencePage(
        page_id=page_id,
        title=title,
        body_html=content,          # plain text is fine — html_to_text handles it
        space_key=space_key,
        space_name=space_name,
        url=url,
        last_modified=datetime.now(timezone.utc),
        version=1,
        labels=[],
        ancestor_titles=[],
    )


def _title_from_content(text: str) -> str | None:
    """Extract the first heading or first non-empty line as title."""
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("#"):
            return line.lstrip("#").strip()
        if line:
            return line[:80]
    return None


def _load_doc(path: Path) -> list[ConfluencePage]:
    """Load a Confluence MIME-export .doc file (HTML inside MIME envelope)."""
    raw = path.read_bytes()

    # Check if it's a MIME message (Confluence export) or plain text
    if raw[:5] == b"Date:" or raw[:5] == b"MIME-" or raw[:8] == b"Message-":
        return _parse_confluence_mime(path, raw)

    # Fallback: try reading as plain text
    content = raw.decode("utf-8", errors="replace").strip()
    if not content:
        return []
    return [_make_page(
        page_id=f"local_{path.stem}",
        title=_title_from_filename(path) or path.stem,
        content=content,
        url=path.resolve().as_uri(),
        space_key="LOCAL",
        space_name="Local Documents",
    )]


def _parse_confluence_mime(path: Path, raw: bytes) -> list[ConfluencePage]:
    """Parse Confluence MIME-export format and extract HTML content."""
    msg = email.message_from_bytes(raw)

    html_content = ""
    title = ""

    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            if ct == "text/html":
                payload = part.get_payload(decode=False)
                encoding = part.get("Content-Transfer-Encoding", "").lower()

                if isinstance(payload, bytes):
                    html_content = payload.decode("utf-8", errors="replace")
                elif isinstance(payload, str):
                    if encoding == "quoted-printable":
                        html_content = quopri.decodestring(payload.encode()).decode("utf-8", errors="replace")
                    else:
                        html_content = payload
                break
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            html_content = payload.decode("utf-8", errors="replace")

    if not html_content:
        return []

    # Extract title from <title> tag
    import re
    title_match = re.search(r"<title>(.*?)</title>", html_content, re.IGNORECASE | re.DOTALL)
    if title_match:
        title = title_match.group(1).strip()

    # Convert HTML to plain text using existing parser
    plain_text = html_to_text(html_content)
    if not plain_text.strip():
        return []

    # Clean up title from filename if not found in HTML
    if not title:
        title = _title_from_filename(path) or path.stem

    return [_make_page(
        page_id=f"local_{path.stem}",
        title=title,
        content=plain_text,
        url=path.resolve().as_uri(),
        space_key="LOCAL",
        space_name="Local Documents",
    )]


def _load_docx(path: Path) -> list[ConfluencePage]:
    """Load a .docx file using python-docx."""
    try:
        from docx import Document
    except ImportError:
        logger.warning("Skipping %s — python-docx not installed", path.name)
        return []

    doc = Document(str(path))
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    content = "\n\n".join(paragraphs).strip()
    if not content:
        return []

    return [_make_page(
        page_id=f"local_{path.stem}",
        title=_title_from_content(content) or _title_from_filename(path) or path.stem,
        content=content,
        url=path.resolve().as_uri(),
        space_key="LOCAL",
        space_name="Local Documents",
    )]


def _title_from_filename(path: Path) -> str | None:
    """Convert URL-encoded filename to a readable title."""
    name = path.stem
    # Decode URL-encoded characters (+ → space)
    name = name.replace("+", " ").replace("%20", " ")
    # Remove leading/trailing dashes and spaces
    name = name.strip("- ")
    return name if name else None
