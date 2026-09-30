"""Tests for RRF, per-source-type limits, and <user_data> prompt injection defense."""
from __future__ import annotations
import pytest

from app.models.schemas import SourceDocument
from app.services.vector_store import (
    reciprocal_rank_fusion,
    apply_source_type_limits,
)


def _doc(page_id: str, score: float = 0.8, space_key: str = "ENG") -> SourceDocument:
    return SourceDocument(
        page_id=page_id,
        title=f"Page {page_id}",
        url=f"https://example.com/{page_id}",
        space_key=space_key,
        space_name="Test",
        excerpt="excerpt",
        content="content",
        score=score,
    )


# ── Reciprocal Rank Fusion ────────────────────────────────────────────────


class TestReciprocalRankFusion:
    def test_docs_in_both_lists_rank_higher(self):
        vector = [_doc("A", 0.9), _doc("B", 0.8), _doc("C", 0.7)]
        keyword = [_doc("C", 0.65), _doc("A", 0.65), _doc("D", 0.50)]
        result = reciprocal_rank_fusion(vector, keyword)
        ids = [d.page_id for d in result]
        # A and C appear in both — should be top 2
        assert ids[0] in ("A", "C")
        assert ids[1] in ("A", "C")
        assert set(ids[:2]) == {"A", "C"}

    def test_preserves_all_documents(self):
        vector = [_doc("A"), _doc("B")]
        keyword = [_doc("C"), _doc("D")]
        result = reciprocal_rank_fusion(vector, keyword)
        assert len(result) == 4
        assert {d.page_id for d in result} == {"A", "B", "C", "D"}

    def test_empty_vector_results(self):
        vector = []
        keyword = [_doc("A"), _doc("B")]
        result = reciprocal_rank_fusion(vector, keyword)
        assert len(result) == 2

    def test_empty_keyword_results(self):
        vector = [_doc("A"), _doc("B")]
        keyword = []
        result = reciprocal_rank_fusion(vector, keyword)
        assert len(result) == 2

    def test_both_empty(self):
        result = reciprocal_rank_fusion([], [])
        assert result == []

    def test_single_doc_in_both(self):
        vector = [_doc("A", 0.9)]
        keyword = [_doc("A", 0.65)]
        result = reciprocal_rank_fusion(vector, keyword)
        assert len(result) == 1
        assert result[0].page_id == "A"
        # Should have the vector version (higher score)
        assert result[0].score == 0.9

    def test_rank_order_matters(self):
        # A is rank 1 in vector, B is rank 1 in keyword
        vector = [_doc("A"), _doc("B")]
        keyword = [_doc("B"), _doc("A")]
        result = reciprocal_rank_fusion(vector, keyword)
        # Both appear in both lists, but A is rank1+rank2, B is rank2+rank1
        # They should have equal RRF scores
        assert len(result) == 2


# ── Per-Source-Type Limits ────────────────────────────────────────────────


class TestSourceTypeLimits:
    def test_caps_github_at_4(self):
        docs = [_doc(f"g{i}", space_key="__GITHUB__") for i in range(8)]
        result = apply_source_type_limits(docs)
        assert len(result) == 4

    def test_caps_jira_at_4(self):
        docs = [_doc(f"j{i}", space_key="__JIRA__") for i in range(6)]
        result = apply_source_type_limits(docs)
        assert len(result) == 4

    def test_confluence_not_capped(self):
        docs = [_doc(f"c{i}", space_key="ENG") for i in range(10)]
        result = apply_source_type_limits(docs)
        assert len(result) == 10

    def test_mixed_sources_all_get_slots(self):
        docs = (
            [_doc(f"g{i}", space_key="__GITHUB__") for i in range(6)]
            + [_doc(f"c{i}", space_key="ENG") for i in range(3)]
            + [_doc(f"j{i}", space_key="__JIRA__") for i in range(5)]
        )
        result = apply_source_type_limits(docs)
        github_count = sum(1 for d in result if d.space_key == "__GITHUB__")
        jira_count = sum(1 for d in result if d.space_key == "__JIRA__")
        confluence_count = sum(1 for d in result if d.space_key == "ENG")
        assert github_count == 4
        assert jira_count == 4
        assert confluence_count == 3

    def test_empty_list(self):
        assert apply_source_type_limits([]) == []

    def test_upload_capped_at_3(self):
        docs = [_doc(f"u{i}", space_key="__UPLOAD__") for i in range(5)]
        result = apply_source_type_limits(docs)
        assert len(result) == 3

    def test_preserves_order(self):
        docs = [_doc("A", space_key="__GITHUB__"), _doc("B", space_key="ENG"), _doc("C", space_key="__GITHUB__")]
        result = apply_source_type_limits(docs)
        assert [d.page_id for d in result] == ["A", "B", "C"]


# ── <user_data> Tag Defense ───────────────────────────────────────────────


class TestUserDataTags:
    def test_system_prompt_mentions_user_data_tags(self):
        from app.services.llm import _DEFAULT_SYSTEM_PROMPT
        assert "<user_data>" in _DEFAULT_SYSTEM_PROMPT

    def test_security_suffix_mentions_user_data_tags(self):
        from app.services.llm import LLMService
        assert "<user_data>" in LLMService._SECURITY_RULES_SUFFIX
