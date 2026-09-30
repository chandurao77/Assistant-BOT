"""Tests for contextual chunking — enriched text with metadata prefix."""
from datetime import datetime, timezone

import pytest

from app.models.document import DocumentChunk
from app.utils.text_splitter import Chunk, split_text


# ── text_splitter: section heading tracking ──────────────────────────────


class TestSplitTextSectionHeadings:
    def test_heading_propagated_to_chunk(self):
        text = "## Architecture\n\nThe system uses microservices."
        chunks = split_text(text, chunk_size=100)
        assert len(chunks) >= 1
        assert chunks[0].section_heading == "Architecture"

    def test_multiple_headings(self):
        text = (
            "## Intro\n\nSome intro text.\n\n"
            "## Design\n\nSome design text."
        )
        chunks = split_text(text, chunk_size=5)  # small chunk_size to force split
        headings = [c.section_heading for c in chunks]
        assert "Intro" in headings
        assert "Design" in headings

    def test_no_heading(self):
        text = "Just some plain text without any headings at all."
        chunks = split_text(text, chunk_size=100)
        assert len(chunks) >= 1
        assert chunks[0].section_heading == ""

    def test_heading_carries_forward(self):
        """Chunks after a heading should inherit it until a new heading appears."""
        # Build text with one heading and enough content to span multiple chunks
        long_body = " ".join(f"word{i}" for i in range(200))
        text = f"# Overview\n\n{long_body}"
        chunks = split_text(text, chunk_size=50, chunk_overlap=5)
        assert len(chunks) >= 2
        for c in chunks:
            assert c.section_heading == "Overview"

    def test_h1_through_h6(self):
        for level in range(1, 7):
            prefix = "#" * level
            text = f"{prefix} Heading Level {level}\n\nSome content here."
            chunks = split_text(text, chunk_size=100)
            assert chunks[0].section_heading == f"Heading Level {level}"

    def test_chunk_dataclass_has_section_heading(self):
        c = Chunk(text="hello", index=0, section_heading="Intro")
        assert c.section_heading == "Intro"

    def test_chunk_default_section_heading(self):
        c = Chunk(text="hello", index=0)
        assert c.section_heading == ""


# ── DocumentChunk: enrich_text ───────────────────────────────────────────


def _make_chunk(**overrides) -> DocumentChunk:
    defaults = dict(
        chunk_id="page1_0",
        page_id="page1",
        title="Acme Retry Patterns",
        space_key="ENG",
        space_name="Acme Team",
        url="https://wiki.example.com/page1",
        text="Retry logic uses exponential backoff with jitter.",
        chunk_index=0,
        total_chunks=1,
        last_modified=datetime(2026, 1, 1, tzinfo=timezone.utc),
        section_heading="Error Handling",
    )
    defaults.update(overrides)
    return DocumentChunk(**defaults)


class TestEnrichText:
    def test_enriches_with_all_fields(self):
        chunk = _make_chunk()
        chunk.enrich_text()
        assert chunk.text.startswith("Source: Acme Retry Patterns | Space: Acme Team | Section: Error Handling | ")
        assert "Retry logic uses exponential backoff" in chunk.text

    def test_preserves_raw_text(self):
        chunk = _make_chunk()
        original = chunk.text
        chunk.enrich_text()
        assert chunk.raw_text == original
        assert chunk.raw_text != chunk.text

    def test_no_section_heading(self):
        chunk = _make_chunk(section_heading="")
        chunk.enrich_text()
        assert "Section:" not in chunk.text
        assert chunk.text.startswith("Source: Acme Retry Patterns | Space: Acme Team | ")

    def test_no_space_name(self):
        chunk = _make_chunk(space_name="")
        chunk.enrich_text()
        assert "Space:" not in chunk.text
        assert chunk.text.startswith("Source: Acme Retry Patterns | Section: Error Handling | ")

    def test_only_title(self):
        chunk = _make_chunk(space_name="", section_heading="")
        chunk.enrich_text()
        assert chunk.text.startswith("Source: Acme Retry Patterns | Retry logic")


# ── DocumentChunk: to_qdrant_payload ─────────────────────────────────────


class TestToQdrantPayload:
    def test_payload_includes_raw_text(self):
        chunk = _make_chunk()
        chunk.enrich_text()
        payload = chunk.to_qdrant_payload()
        assert "raw_text" in payload
        assert payload["raw_text"] == "Retry logic uses exponential backoff with jitter."
        assert payload["text"] != payload["raw_text"]
        assert payload["text"].startswith("Source:")

    def test_payload_raw_text_fallback(self):
        """When not enriched, raw_text should equal text."""
        chunk = _make_chunk()
        payload = chunk.to_qdrant_payload()
        assert payload["raw_text"] == payload["text"]

    def test_payload_has_all_fields(self):
        chunk = _make_chunk()
        chunk.enrich_text()
        payload = chunk.to_qdrant_payload()
        required = {"chunk_id", "page_id", "title", "space_key", "space_name",
                     "url", "text", "raw_text", "chunk_index", "total_chunks", "last_modified",
                     "page_type", "labels", "ancestor_titles"}
        assert required.issubset(set(payload.keys()))

    def test_payload_page_type_inferred_from_title(self):
        """page_type should be inferred from title when not explicitly set."""
        chunk = _make_chunk()
        chunk.title = "Developer Guide to Onboarding"
        payload = chunk.to_qdrant_payload()
        assert payload["page_type"] == "howto"

    def test_payload_page_type_explicit_overrides_inference(self):
        """Explicitly set page_type should be stored as-is (not re-classified)."""
        chunk = _make_chunk()
        chunk.page_type = "reference"
        payload = chunk.to_qdrant_payload()
        assert payload["page_type"] == "reference"

    def test_payload_labels_stored(self):
        chunk = _make_chunk()
        chunk.labels = ["official", "canonical"]
        payload = chunk.to_qdrant_payload()
        assert payload["labels"] == ["official", "canonical"]

    def test_payload_ancestor_titles_stored(self):
        chunk = _make_chunk()
        chunk.ancestor_titles = ["Engineering Docs", "Backend"]
        payload = chunk.to_qdrant_payload()
        assert payload["ancestor_titles"] == ["Engineering Docs", "Backend"]


# ── Integration: split_text → DocumentChunk → enrich ─────────────────────


class TestEndToEnd:
    def test_split_and_enrich(self):
        """Full pipeline: HTML-like text with headings → split → enrich → payload."""
        text = (
            "## Getting Started\n\n"
            "Install Docker and run the compose stack.\n\n"
            "## Configuration\n\n"
            "Set environment variables in .env file."
        )
        raw_chunks = split_text(text, chunk_size=100)
        doc_chunks = [
            DocumentChunk(
                chunk_id=f"p1_{c.index}",
                page_id="p1",
                title="Setup Guide",
                space_key="DOC",
                space_name="Documentation",
                url="",
                text=c.text,
                chunk_index=c.index,
                total_chunks=len(raw_chunks),
                last_modified=datetime(2026, 1, 1, tzinfo=timezone.utc),
                section_heading=c.section_heading,
            )
            for c in raw_chunks
        ]

        for chunk in doc_chunks:
            chunk.enrich_text()

        # Verify enrichment
        for chunk in doc_chunks:
            assert chunk.text.startswith("Source: Setup Guide")
            assert chunk.raw_text  # Original text preserved
            assert "Source:" not in chunk.raw_text

        # Verify payload structure
        payload = doc_chunks[0].to_qdrant_payload()
        assert payload["raw_text"] != payload["text"]
        assert "Source:" in payload["text"]
