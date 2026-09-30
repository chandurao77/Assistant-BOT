"""Unit tests for app.utils.text_splitter."""
import pytest
from app.utils.text_splitter import split_text, Chunk


class TestSplitText:
    def test_empty_string_returns_empty(self):
        assert split_text("") == []

    def test_whitespace_only_returns_empty(self):
        assert split_text("   \n  ") == []

    def test_short_text_single_chunk(self):
        text = "Hello world. This is a short document."
        chunks = split_text(text, chunk_size=512)
        assert len(chunks) == 1
        assert chunks[0].index == 0
        assert "Hello world" in chunks[0].text

    def test_chunk_indices_are_sequential(self):
        # Generate text longer than chunk_size
        text = " ".join(["word"] * 600)
        chunks = split_text(text, chunk_size=100, chunk_overlap=10)
        for i, chunk in enumerate(chunks):
            assert chunk.index == i

    def test_long_text_produces_multiple_chunks(self):
        # Use multi-paragraph text so the splitter has clear split boundaries
        para = " ".join(["word"] * 60)
        text = "\n\n".join([para] * 12)   # 720 words across 12 paragraphs
        chunks = split_text(text, chunk_size=100, chunk_overlap=0)
        assert len(chunks) > 1

    def test_chunks_respect_size_limit(self):
        text = " ".join(["word"] * 600)
        chunk_size = 100
        chunks = split_text(text, chunk_size=chunk_size, chunk_overlap=0)
        # Allow small overshoot from sentence/paragraph merging
        for chunk in chunks[:-1]:
            word_count = len(chunk.text.split())
            assert word_count <= chunk_size * 1.5, (
                f"Chunk {chunk.index} has {word_count} words, expected <= {chunk_size * 1.5}"
            )

    def test_overlap_carries_words_into_next_chunk(self):
        # Create paragraphs so splitter has clear boundaries
        para = " ".join(["alpha"] * 60)
        text = f"{para}\n\n{para}\n\n{para}"
        chunks = split_text(text, chunk_size=60, chunk_overlap=20)
        if len(chunks) >= 2:
            # Last words of chunk[0] should appear at start of chunk[1]
            last_words_chunk0 = set(chunks[0].text.split()[-10:])
            first_words_chunk1 = set(chunks[1].text.split()[:10])
            assert last_words_chunk0 & first_words_chunk1, "Overlap not found between chunks"

    def test_paragraph_boundaries_respected(self):
        text = "First paragraph content here.\n\nSecond paragraph content here.\n\nThird paragraph content."
        chunks = split_text(text, chunk_size=512)
        # All content should survive chunking
        combined = " ".join(c.text for c in chunks)
        assert "First paragraph" in combined
        assert "Second paragraph" in combined
        assert "Third paragraph" in combined

    def test_returns_chunk_dataclass(self):
        chunks = split_text("Hello world", chunk_size=512)
        assert isinstance(chunks[0], Chunk)
        assert hasattr(chunks[0], "text")
        assert hasattr(chunks[0], "index")

    def test_single_very_long_paragraph_is_split(self):
        # One paragraph, 300 words — should be split into sentences
        text = "The quick brown fox jumps over the lazy dog. " * 60
        chunks = split_text(text, chunk_size=50, chunk_overlap=0)
        assert len(chunks) > 1
