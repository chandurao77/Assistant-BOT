"""Sentence-aware recursive text splitter for Confluence content."""
from __future__ import annotations
import re
from dataclasses import dataclass


@dataclass
class Chunk:
    text: str
    index: int
    section_heading: str = ""


# Regex to detect markdown-style headings (e.g. "# Heading", "## Sub-heading")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)


def split_text(
    text: str,
    chunk_size: int = 512,
    chunk_overlap: int = 64,
) -> list[Chunk]:
    """
    Split text into overlapping chunks while respecting sentence boundaries.

    Strategy:
    1. Split on paragraph breaks first
    2. If a paragraph exceeds chunk_size, fall back to sentence splitting
    3. Greedily merge short paragraphs/sentences up to chunk_size
    4. Apply overlap by carrying the last `chunk_overlap` chars into the next chunk
    """
    if not text or not text.strip():
        return []

    # Tokenise into atomic units (paragraphs, then sentences)
    # Track the last-seen section heading for each unit.
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
    units: list[str] = []
    unit_headings: list[str] = []          # parallel list — heading for each unit
    _current_heading = ""
    for para in paragraphs:
        # Detect heading lines (e.g. "## Architecture")
        m = _HEADING_RE.match(para)
        if m:
            _current_heading = m.group(2).strip()
        if _word_count(para) <= chunk_size:
            units.append(para)
            unit_headings.append(_current_heading)
        else:
            # Split long paragraphs into sentences
            sentences = re.split(r"(?<=[.!?])\s+", para)
            for s in sentences:
                s = s.strip()
                if s:
                    units.append(s)
                    unit_headings.append(_current_heading)

    # Greedily pack units into chunks
    chunks: list[str] = []
    chunk_headings: list[str] = []         # heading for each packed chunk
    current_parts: list[str] = []
    current_size = 0
    current_heading = ""

    for unit, heading in zip(units, unit_headings):
        unit_size = _word_count(unit)
        if current_size + unit_size > chunk_size and current_parts:
            chunks.append(" ".join(current_parts))
            chunk_headings.append(current_heading)
            # Overlap: keep last N words of current chunk
            overlap_text = _last_n_words(" ".join(current_parts), chunk_overlap)
            current_parts = [overlap_text, unit] if overlap_text else [unit]
            current_size = _word_count(" ".join(current_parts))
            current_heading = heading
        else:
            current_parts.append(unit)
            current_size += unit_size
            if not current_heading:
                current_heading = heading

    if current_parts:
        chunks.append(" ".join(current_parts))
        chunk_headings.append(current_heading)

    return [
        Chunk(text=c, index=i, section_heading=h)
        for i, (c, h) in enumerate(zip(chunks, chunk_headings))
        if c.strip()
    ]


def _word_count(text: str) -> int:
    return len(text.split())


def _last_n_words(text: str, n: int) -> str:
    words = text.split()
    return " ".join(words[-n:]) if len(words) >= n else " ".join(words)
