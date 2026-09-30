"""Internal document model used through the ingestion and retrieval pipeline."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
import re


def classify_page_type(title: str) -> str:
    """Classify a page title into a type using priority-ordered keyword matching.

    Priority order (first match wins):
    1. howto      — instructional guides, setup pages, tutorials
    2. reference  — API docs, architecture, security, config specs
    3. report     — status updates, release notes, quarterly reports
    4. general    — everything else
    """
    t = title.lower()

    howto_patterns = [
        r"\bhow\s+to\b", r"\bhow\s+do\b", r"\bgetting\s+started\b",
        r"\bguide\b", r"\btutorial\b", r"\binstallation\b",
        r"\bonboarding\b", r"\bsetup\b", r"\bquickstart\b",
        r"\bstep[s]?\s+to\b", r"\buser\s+guide\b", r"\bplaybook\b",
    ]
    for pat in howto_patterns:
        if re.search(pat, t):
            return "howto"

    reference_patterns = [
        r"\bapi\b", r"\barchitecture\b", r"\breference\b",
        r"\bpolicy\b", r"\bconfigur", r"\bspecification\b",
        r"\bschema\b", r"\bendpoint[s]?\b", r"\bdata\s+model\b",
        r"\bdesign\s+doc\b", r"\bsecurity\b", r"\bauthentication\b",
        r"\bauthorization\b", r"\bintegration\b",
    ]
    for pat in reference_patterns:
        if re.search(pat, t):
            return "reference"

    report_patterns = [
        r"\bq[1-4]\b", r"\brelease\s+notes?\b", r"\bbacklog\b",
        r"\bpriorities\b", r"\bstatus\s+wiki\b", r"\bstatus\s+report\b",
        r"\bmeeting\s+notes?\b", r"\bsprint\s+(review|retro|planning)\b",
        r"\b20\d{2}\s*[|]\s*q[1-4]\b",
        r"\bweekly\s+update\b", r"\bmonthly\s+update\b",
        r"\bchangelog\b",
    ]
    for pat in report_patterns:
        if re.search(pat, t):
            return "report"

    return "general"


@dataclass
class ConfluencePage:
    """Raw page fetched from Confluence API."""
    page_id: str
    title: str
    body_html: str
    space_key: str
    space_name: str
    url: str
    last_modified: datetime
    version: int
    labels: list[str] = field(default_factory=list)
    ancestor_titles: list[str] = field(default_factory=list)


@dataclass
class DocumentChunk:
    """A chunked piece of a Confluence page ready for embedding."""
    chunk_id: str                  # "{page_id}_{chunk_index}"
    page_id: str
    title: str
    space_key: str
    space_name: str
    url: str
    text: str                      # clean plain text (enriched when contextual chunking is on)
    chunk_index: int
    total_chunks: int
    last_modified: datetime
    section_heading: str = ""
    raw_text: str = ""             # original chunk text preserved for citation display
    # Enriched ingestion metadata — stored in Qdrant for query-time use
    page_type: str = ""            # "howto" / "reference" / "report" / "general"
    labels: list[str] = field(default_factory=list)          # Confluence page labels
    ancestor_titles: list[str] = field(default_factory=list) # Breadcrumb hierarchy
    # OKF semantic graph fields (populated only for OKF-converted pages)
    related_concepts: list[str] = field(default_factory=list) # [[ConceptName]] links from OKF
    okf_converted: bool = False    # True when chunk came from an OKF-structured source

    def enrich_text(self) -> None:
        """Prepend contextual metadata to the chunk text for better retrieval.

        Stores the original text in ``raw_text`` and replaces ``text`` with
        an enriched version:
        ``Source: {title} | Space: {space_name} | Section: {heading} | {text}``
        """
        self.raw_text = self.text
        parts = [f"Source: {self.title}"]
        if self.space_name:
            parts.append(f"Space: {self.space_name}")
        if self.section_heading:
            parts.append(f"Section: {self.section_heading}")
        prefix = " | ".join(parts)
        self.text = f"{prefix} | {self.raw_text}"

    def to_qdrant_payload(self) -> dict:
        return {
            "chunk_id": self.chunk_id,
            "page_id": self.page_id,
            "title": self.title,
            "space_key": self.space_key,
            "space_name": self.space_name,
            "url": self.url,
            "text": self.text,
            "raw_text": self.raw_text or self.text,
            "chunk_index": self.chunk_index,
            "total_chunks": self.total_chunks,
            "last_modified": self.last_modified.isoformat(),
            # Enriched metadata
            "page_type": self.page_type or classify_page_type(self.title),
            "labels": self.labels,
            "ancestor_titles": self.ancestor_titles,
            # OKF semantic graph fields (absent on non-OKF chunks → Qdrant ignores missing keys)
            "related_concepts": self.related_concepts,
            "okf_converted": self.okf_converted,
        }
