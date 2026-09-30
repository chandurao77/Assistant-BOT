"""OKF-aware section-based chunker.

Splits OKF Markdown files by ``##`` section headings instead of fixed token
windows.  Each chunk carries its section name, document title, and all
existing GraphRAG metadata.

Minimum chunk size: 50 tokens (skip empty/trivial sections).
Maximum chunk size: 800 tokens (split large sections at paragraph boundaries).
Embedding prefix: ``"[Title] > [Section]: [content]"``
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

from app.models.document import DocumentChunk, classify_page_type

# Rough token estimate: 1 token ≈ 4 characters (good enough for size gating)
_CHARS_PER_TOKEN = 4
_MIN_TOKENS = 50
_MAX_TOKENS = 800
_MIN_CHARS = _MIN_TOKENS * _CHARS_PER_TOKEN     # 200
_MAX_CHARS = _MAX_TOKENS * _CHARS_PER_TOKEN     # 3200

# Regex to split on ## section boundaries
_SECTION_RE = re.compile(r"^(#{2})\s+(.+)$", re.MULTILINE)
# Regex to extract related concepts from ## Related Concepts
_RELATED_RE = re.compile(r"\[\[(.+?)\]\]")
# Regex to extract status from ## Metadata
_STATUS_RE = re.compile(r"[-*]\s*Status:\s*(\w+)", re.IGNORECASE)


@dataclass
class OKFSection:
    """One parsed section from an OKF Markdown document."""
    title: str          # Document-level title (from # heading)
    section: str        # Section name (from ## heading)
    content: str        # Raw section text (without the ## line)
    related_concepts: list[str] = field(default_factory=list)
    status: str = "active"


def parse_okf_sections(okf_markdown: str) -> list[OKFSection]:
    """Parse an OKF Markdown document into its constituent ## sections.

    Args:
        okf_markdown: Full OKF document text starting with # Title.

    Returns:
        List of OKFSection objects, one per ## heading.
        The document-level title (# heading) is propagated to all sections.
    """
    if not okf_markdown.strip():
        return []

    # Extract document title from first # line
    title = ""
    for line in okf_markdown.splitlines():
        line = line.strip()
        if line.startswith("# ") and not line.startswith("## "):
            title = line.lstrip("# ").strip()
            break

    # Extract all related concepts (from ## Related Concepts section)
    related: list[str] = []
    related_section = re.search(
        r"## Related Concepts\s*\n(.*?)(?=\n##|\Z)",
        okf_markdown, re.DOTALL,
    )
    if related_section:
        related = _RELATED_RE.findall(related_section.group(1))

    # Extract status from ## Metadata section
    status = "active"
    metadata_section = re.search(
        r"## Metadata\s*\n(.*?)(?=\n##|\Z)",
        okf_markdown, re.DOTALL,
    )
    if metadata_section:
        sm = _STATUS_RE.search(metadata_section.group(1))
        if sm:
            status = sm.group(1).lower()

    # Split into sections at ## boundaries
    positions = [(m.start(), m.group(2)) for m in _SECTION_RE.finditer(okf_markdown)]

    sections: list[OKFSection] = []
    for i, (start, section_name) in enumerate(positions):
        end = positions[i + 1][0] if i + 1 < len(positions) else len(okf_markdown)
        # Content is everything after the ## heading line
        raw = okf_markdown[start:end]
        # Strip the ## heading line itself
        content_lines = raw.splitlines()[1:]
        content = "\n".join(content_lines).strip()

        sections.append(OKFSection(
            title=title,
            section=section_name,
            content=content,
            related_concepts=related,
            status=status,
        ))

    return sections


class OKFAwareChunker:
    """Convert OKF Markdown sections into DocumentChunk objects.

    Each chunk represents one OKF section.  Large sections are split at
    paragraph boundaries to stay within ``max_tokens``.  Tiny sections
    below ``min_tokens`` are skipped.

    Args:
        min_tokens: Skip sections with fewer tokens than this (default: 50).
        max_tokens: Split sections larger than this at paragraph boundaries (default: 800).
    """

    def __init__(
        self,
        min_tokens: int = _MIN_TOKENS,
        max_tokens: int = _MAX_TOKENS,
    ) -> None:
        self._min_chars = min_tokens * _CHARS_PER_TOKEN
        self._max_chars = max_tokens * _CHARS_PER_TOKEN

    def chunk(
        self,
        okf_markdown: str,
        page_id: str,
        space_key: str,
        space_name: str,
        url: str,
        last_modified: datetime,
        labels: list[str] | None = None,
        ancestor_titles: list[str] | None = None,
    ) -> list[DocumentChunk]:
        """Convert a full OKF document into DocumentChunk objects.

        Args:
            okf_markdown: Full OKF Markdown text.
            page_id: Confluence page ID.
            space_key: Confluence space key.
            space_name: Human-readable space name.
            url: Canonical page URL.
            last_modified: Page last-modified datetime.
            labels: Confluence labels (from original page).
            ancestor_titles: Breadcrumb hierarchy (from original page).

        Returns:
            List of DocumentChunk objects ready for embedding and upsert.
        """
        sections = parse_okf_sections(okf_markdown)
        if not sections:
            return []

        # Extract title from first section (they all share it)
        title = sections[0].title or "Untitled"
        page_type = classify_page_type(title)
        related_concepts = sections[0].related_concepts

        # Build chunks from sections — split large sections at paragraph boundaries
        raw_chunks: list[tuple[str, str]] = []  # (section_name, content)
        for sec in sections:
            # Skip Metadata and Related Concepts sections (not useful for retrieval)
            if sec.section.lower() in ("metadata", "related concepts"):
                continue
            if not sec.content or sec.content.strip() in ("N/A", "None", ""):
                continue

            sub_chunks = self._split_section(sec.section, sec.content)
            raw_chunks.extend(sub_chunks)

        # Filter empty / too-short chunks
        raw_chunks = [
            (sec, txt) for sec, txt in raw_chunks
            if len(txt) >= self._min_chars
        ]

        total = len(raw_chunks)
        if total == 0:
            return []

        doc_chunks: list[DocumentChunk] = []
        for idx, (section_name, content) in enumerate(raw_chunks):
            # Embedding prefix: "[Title] > [Section]: content"
            enriched = f"{title} > {section_name}: {content}"

            chunk = DocumentChunk(
                chunk_id=f"{page_id}_{idx}",
                page_id=page_id,
                title=title,
                space_key=space_key,
                space_name=space_name,
                url=url,
                text=enriched,
                raw_text=content,
                chunk_index=idx,
                total_chunks=total,
                last_modified=last_modified,
                section_heading=section_name,
                page_type=page_type,
                labels=labels or [],
                ancestor_titles=ancestor_titles or [],
            )
            # Attach OKF-specific fields (dataclass fields added in document.py)
            chunk.related_concepts = related_concepts
            chunk.okf_converted = True
            doc_chunks.append(chunk)

        return doc_chunks

    def _split_section(self, section_name: str, content: str) -> list[tuple[str, str]]:
        """Split a single section at paragraph boundaries if it exceeds max_chars."""
        if len(content) <= self._max_chars:
            return [(section_name, content)]

        # Split on double newlines (paragraph boundaries)
        paragraphs = [p.strip() for p in re.split(r"\n{2,}", content) if p.strip()]
        chunks: list[tuple[str, str]] = []
        current: list[str] = []
        current_len = 0

        for para in paragraphs:
            if current_len + len(para) > self._max_chars and current:
                chunks.append((section_name, "\n\n".join(current)))
                current = [para]
                current_len = len(para)
            else:
                current.append(para)
                current_len += len(para)

        if current:
            chunks.append((section_name, "\n\n".join(current)))

        return chunks
