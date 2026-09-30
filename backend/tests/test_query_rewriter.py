"""Tests for the query rewriter — vague question detection and rewriting."""
from __future__ import annotations

import pytest

from app.services.query_rewriter import needs_rewrite, rewrite_query, _REWRITE_SYSTEM_PROMPT


class TestNeedsRewrite:
    """Test the heuristic that decides if a question should be rewritten."""

    # ── Should rewrite (vague/short) ──────────────────────────────────────

    def test_short_vague_question(self):
        assert needs_rewrite("what reports we have") is True

    def test_very_short_question(self):
        assert needs_rewrite("how does it work") is True

    def test_two_word_question(self):
        assert needs_rewrite("list everything") is True

    def test_single_word(self):
        assert needs_rewrite("architecture") is True

    # ── Should NOT rewrite (specific enough) ──────────────────────────────

    def test_long_specific_question(self):
        assert needs_rewrite("What is the onboarding process for new backend engineers joining the platform team") is False

    def test_seven_word_question(self):
        assert needs_rewrite("How does the RAG pipeline handle errors") is False

    def test_jira_ticket_reference(self):
        assert needs_rewrite("What is MESH-123") is False

    def test_camel_case_identifier(self):
        assert needs_rewrite("explain ChatContainer") is False

    def test_dotted_path(self):
        assert needs_rewrite("what is app.services.rag") is False

    def test_snake_case_identifier(self):
        assert needs_rewrite("explain query_rewrite_service") is False


class TestRewritePrompt:
    """Ensure the rewrite prompt is hardcoded and safe."""

    def test_prompt_is_not_empty(self):
        assert len(_REWRITE_SYSTEM_PROMPT) > 50

    def test_prompt_contains_rules(self):
        assert "Rules:" in _REWRITE_SYSTEM_PROMPT

    def test_prompt_prevents_extra_output(self):
        assert "ONLY the rewritten query" in _REWRITE_SYSTEM_PROMPT


class TestRewriteQuerySkips:
    """Test that rewrite_query returns None when not needed."""

    @pytest.mark.asyncio
    async def test_skips_long_questions(self):
        from app.config import Settings
        settings = Settings(environment="test")
        result = await rewrite_query(
            "How does the RAG pipeline handle errors when Ollama is unavailable",
            settings,
        )
        assert result is None  # Skipped by heuristic, no LLM call made

    @pytest.mark.asyncio
    async def test_skips_jira_references(self):
        from app.config import Settings
        settings = Settings(environment="test")
        result = await rewrite_query("What is MESH-123", settings)
        assert result is None
