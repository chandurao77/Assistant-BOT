"""Tests for BM25 scoring module."""
import math

import pytest

from app.services.bm25 import BM25Index, BM25Scorer, _K1, _B, tokenize


# ── tokenize ──────────────────────────────────────────────────────────────


class TestTokenize:
    def test_basic_tokenization(self):
        assert tokenize("Hello World") == ["hello", "world"]

    def test_removes_stop_words(self):
        result = tokenize("the quick brown fox is a very fast animal")
        assert "the" not in result
        assert "is" not in result
        assert "quick" in result
        assert "brown" in result

    def test_removes_short_tokens(self):
        result = tokenize("I a am ok go to do it")
        # single char tokens removed, "am" kept (len >= 2), stop words removed
        assert "ok" in result

    def test_empty_string(self):
        assert tokenize("") == []

    def test_preserves_numbers(self):
        result = tokenize("version 12 release 3")
        assert "version" in result
        assert "12" in result
        assert "release" in result

    def test_handles_punctuation(self):
        result = tokenize("hello, world! how's it going?")
        assert "hello" in result
        assert "world" in result
        assert "going" in result


# ── BM25Index ─────────────────────────────────────────────────────────────


def _make_payloads(*texts: str) -> list[dict]:
    """Helper to create payload dicts from text strings."""
    return [
        {
            "page_id": f"page_{i}",
            "title": f"Title {i}",
            "text": text,
            "url": f"https://example.com/{i}",
            "space_key": "TEST",
            "space_name": "Test Space",
            "last_modified": "2026-01-01T00:00:00Z",
        }
        for i, text in enumerate(texts)
    ]


class TestBM25Index:
    def test_idf_common_term(self):
        """A term in every document should have low IDF."""
        scorer = BM25Scorer()
        scorer.build_from_payloads(_make_payloads(
            "python programming language",
            "python web development",
            "python data science",
        ))
        idx = scorer._index
        # "python" appears in all 3 docs
        idf_python = idx.idf("python")
        # "data" appears in 1 doc
        idf_data = idx.idf("data")
        assert idf_data > idf_python

    def test_idf_rare_term(self):
        """A term in one document should have high IDF."""
        scorer = BM25Scorer()
        scorer.build_from_payloads(_make_payloads(
            "common common common",
            "common common rare",
            "common common common",
        ))
        idx = scorer._index
        assert idx.idf("rare") > idx.idf("common")

    def test_idf_missing_term(self):
        """A term not in any document should have IDF of 0."""
        scorer = BM25Scorer()
        scorer.build_from_payloads(_make_payloads("hello world"))
        assert scorer._index.idf("nonexistent") == 0.0

    def test_score_higher_for_more_term_occurrences(self):
        """Document with more query term occurrences should score higher."""
        scorer = BM25Scorer()
        # Doc 0: "retry" appears once, Doc 1: "retry" appears three times
        scorer.build_from_payloads(_make_payloads(
            "retry pattern in Acme",
            "retry retry retry pattern in gateway",
        ))
        idx = scorer._index
        tokens = tokenize("retry pattern")
        score_0 = idx.score(tokens, 0)
        score_1 = idx.score(tokens, 1)
        assert score_1 > score_0

    def test_score_zero_for_no_match(self):
        """Document with no matching terms should score 0."""
        scorer = BM25Scorer()
        scorer.build_from_payloads(_make_payloads("python programming"))
        idx = scorer._index
        tokens = tokenize("kubernetes deployment")
        assert idx.score(tokens, 0) == 0.0

    def test_doc_length_normalization(self):
        """Shorter document with same term should score higher (length normalization)."""
        scorer = BM25Scorer()
        short_text = "retry pattern"
        long_text = "retry pattern " + " ".join(f"word{i}" for i in range(100))
        scorer.build_from_payloads(_make_payloads(short_text, long_text))
        idx = scorer._index
        tokens = tokenize("retry")
        score_short = idx.score(tokens, 0)
        score_long = idx.score(tokens, 1)
        assert score_short > score_long


# ── BM25Scorer ────────────────────────────────────────────────────────────


class TestBM25Scorer:
    def test_build_and_search(self):
        scorer = BM25Scorer()
        scorer.build_from_payloads(_make_payloads(
            "Acme retry pattern with exponential backoff",
            "kubernetes deployment configuration",
            "Acme gateway activation retry logic and error handling",
        ))
        results = scorer.search("Acme retry")
        assert len(results) >= 1
        # Acme + retry docs should come first
        page_ids = [r.page_id for r in results]
        assert "page_0" in page_ids
        assert "page_2" in page_ids

    def test_search_empty_query(self):
        scorer = BM25Scorer()
        scorer.build_from_payloads(_make_payloads("hello world"))
        results = scorer.search("")
        assert results == []

    def test_search_stop_words_only(self):
        scorer = BM25Scorer()
        scorer.build_from_payloads(_make_payloads("hello world"))
        results = scorer.search("the is a")
        assert results == []

    def test_search_no_index(self):
        scorer = BM25Scorer()
        results = scorer.search("anything")
        assert results == []

    def test_search_respects_top_k(self):
        scorer = BM25Scorer()
        scorer.build_from_payloads(_make_payloads(
            "alpha beta gamma",
            "alpha delta epsilon",
            "alpha zeta eta",
        ))
        results = scorer.search("alpha", top_k=2)
        assert len(results) <= 2

    def test_search_space_filter(self):
        scorer = BM25Scorer()
        payloads = [
            {"page_id": "p1", "title": "T1", "text": "retry pattern", "url": "", "space_key": "ENG", "space_name": "Acme", "last_modified": None},
            {"page_id": "p2", "title": "T2", "text": "retry pattern", "url": "", "space_key": "SFA", "space_name": "SFA", "last_modified": None},
        ]
        scorer.build_from_payloads(payloads)
        results = scorer.search("retry", space_keys=["ENG"])
        assert len(results) == 1
        assert results[0].space_key == "ENG"

    def test_deduplicates_by_page_id(self):
        """Multiple chunks from the same page should be deduplicated."""
        scorer = BM25Scorer()
        payloads = [
            {"page_id": "p1", "title": "T1", "text": "retry chunk one", "url": "", "space_key": "T", "space_name": "T", "last_modified": None},
            {"page_id": "p1", "title": "T1", "text": "retry chunk two", "url": "", "space_key": "T", "space_name": "T", "last_modified": None},
            {"page_id": "p2", "title": "T2", "text": "retry chunk three", "url": "", "space_key": "T", "space_name": "T", "last_modified": None},
        ]
        scorer.build_from_payloads(payloads)
        results = scorer.search("retry")
        page_ids = [r.page_id for r in results]
        # p1 should appear only once despite having 2 chunks
        assert page_ids.count("p1") == 1

    def test_invalidate(self):
        scorer = BM25Scorer()
        scorer.build_from_payloads(_make_payloads("hello world"))
        assert scorer.is_built
        scorer.invalidate()
        assert not scorer.is_built

    def test_results_have_correct_fields(self):
        scorer = BM25Scorer()
        scorer.build_from_payloads([{
            "page_id": "pg123",
            "title": "My Page Title",
            "text": "some content here about retry patterns",
            "url": "https://example.com/pg123",
            "space_key": "ENG",
            "space_name": "Acme Team",
            "last_modified": "2026-05-01T00:00:00Z",
        }])
        results = scorer.search("retry patterns")
        assert len(results) == 1
        doc = results[0]
        assert doc.page_id == "pg123"
        assert doc.title == "My Page Title"
        assert doc.url == "https://example.com/pg123"
        assert doc.space_key == "ENG"
        assert doc.space_name == "Acme Team"
        assert doc.score > 0
        assert doc.last_modified == "2026-05-01T00:00:00Z"

    def test_scores_normalized_to_unit_range(self):
        """BM25 scores should be normalized to 0–1 (top result = 1.0)."""
        scorer = BM25Scorer()
        scorer.build_from_payloads(_make_payloads(
            "retry retry retry pattern",
            "retry pattern once",
            "unrelated content here",
        ))
        results = scorer.search("retry pattern")
        assert len(results) >= 2
        # Top result should be 1.0 (max-normalized)
        assert results[0].score == 1.0
        # All scores should be <= 1.0
        for r in results:
            assert 0 < r.score <= 1.0

    def test_title_boosts_relevance(self):
        """Terms appearing in title (via combined indexing) should score higher."""
        scorer = BM25Scorer()
        payloads = [
            {"page_id": "p1", "title": "Retry Patterns", "text": "some unrelated content", "url": "", "space_key": "T", "space_name": "T", "last_modified": None},
            {"page_id": "p2", "title": "Unrelated Title", "text": "some unrelated content", "url": "", "space_key": "T", "space_name": "T", "last_modified": None},
        ]
        scorer.build_from_payloads(payloads)
        results = scorer.search("retry")
        assert len(results) == 1
        assert results[0].page_id == "p1"


# ── BM25 math verification ───────────────────────────────────────────────


class TestBM25Math:
    """Verify BM25 formula matches the standard Okapi BM25 specification."""

    def test_idf_formula(self):
        """IDF = log((N - df + 0.5) / (df + 0.5) + 1)"""
        idx = BM25Index()
        idx.total_docs = 100
        idx.inverted = {"rare": {0}, "common": set(range(50))}
        # rare: df=1, N=100 → log((100-1+0.5)/(1+0.5) + 1)
        expected_rare = math.log((100 - 1 + 0.5) / (1 + 0.5) + 1.0)
        assert abs(idx.idf("rare") - expected_rare) < 1e-10
        # common: df=50, N=100
        expected_common = math.log((100 - 50 + 0.5) / (50 + 0.5) + 1.0)
        assert abs(idx.idf("common") - expected_common) < 1e-10

    def test_score_formula(self):
        """Score = Σ IDF(t) * (tf * (k1+1)) / (tf + k1*(1-b+b*dl/avgdl))"""
        idx = BM25Index()
        idx.total_docs = 2
        idx.avg_doc_len = 5.0
        idx.inverted = {"hello": {0}}
        idx.term_freqs = {"hello": {0: 3}}  # "hello" appears 3 times in doc 0

        from app.services.bm25 import _DocEntry
        idx.docs = [
            _DocEntry(page_id="p0", title="", url="", space_key="", space_name="", text="", raw_text="", last_modified=None, token_count=10),
        ]

        # Manual calculation:
        tf = 3
        dl = 10
        avgdl = 5.0
        idf = math.log((2 - 1 + 0.5) / (1 + 0.5) + 1.0)
        expected = idf * (tf * (_K1 + 1)) / (tf + _K1 * (1 - _B + _B * dl / avgdl))

        actual = idx.score(["hello"], 0)
        assert abs(actual - expected) < 1e-10
