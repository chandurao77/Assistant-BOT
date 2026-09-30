"""Tests for the intent router — keyword-based source classification."""
from __future__ import annotations

import pytest

from app.services.intent_router import (
    classify_intent,
    IntentResult,
    SOURCE_CONFLUENCE,
    SOURCE_JIRA,
    SOURCE_GITHUB,
    ALL_SOURCES,
)


class TestClassifyIntent:
    """Test intent classification for various question types."""

    # ── Jira detection ────────────────────────────────────────────────────

    def test_jira_ticket_reference(self):
        result = classify_intent("What is the status of MESH-123?")
        assert SOURCE_JIRA in result.sources
        assert result.matched_source == SOURCE_JIRA

    def test_jira_keywords(self):
        result = classify_intent("Show me all open jira tickets in the sprint backlog")
        assert SOURCE_JIRA in result.sources
        assert result.matched_source == SOURCE_JIRA

    def test_jira_bug_query(self):
        result = classify_intent("List all bugs assigned to Alice in the current sprint")
        assert SOURCE_JIRA in result.sources

    def test_jira_epic_query(self):
        result = classify_intent("What jira epics are planned for Q3?")
        assert SOURCE_JIRA in result.sources

    # ── GitHub detection ──────────────────────────────────────────────────

    def test_github_pr_query(self):
        result = classify_intent("Show me recent pull requests that were merged in the repo")
        assert SOURCE_GITHUB in result.sources
        assert result.matched_source == SOURCE_GITHUB

    def test_github_code_query(self):
        result = classify_intent("What does the source code in the github repository say about auth?")
        assert SOURCE_GITHUB in result.sources
        assert result.matched_source == SOURCE_GITHUB

    def test_github_ci_query(self):
        result = classify_intent("How is the CI/CD workflow configured in git?")
        assert SOURCE_GITHUB in result.sources

    def test_github_readme_query(self):
        result = classify_intent("What does the README say about the repo setup?")
        assert SOURCE_GITHUB in result.sources

    # ── Confluence detection ──────────────────────────────────────────────

    def test_confluence_docs_query(self):
        result = classify_intent("Find the confluence wiki documentation about onboarding")
        assert SOURCE_CONFLUENCE in result.sources
        assert result.matched_source == SOURCE_CONFLUENCE

    def test_confluence_runbook(self):
        result = classify_intent("Where is the runbook for the production deployment docs?")
        assert SOURCE_CONFLUENCE in result.sources

    # ── All sources (no clear signal) ─────────────────────────────────────

    def test_generic_question(self):
        result = classify_intent("How do I configure authentication?")
        assert set(result.sources) == set(ALL_SOURCES)
        assert result.matched_source is None

    def test_ambiguous_question(self):
        result = classify_intent("What is the latest update?")
        assert len(result.sources) >= 1

    def test_empty_question(self):
        result = classify_intent("")
        assert set(result.sources) == set(ALL_SOURCES)

    # ── Space key filters ─────────────────────────────────────────────────

    def test_jira_space_key_filter(self):
        result = classify_intent("Show me jira tickets in the backlog")
        filters = result.space_key_filters
        # Jira intent includes both Jira + Confluence, so returns None (no filter)
        # because Confluence uses dynamic keys
        assert filters is None or "__JIRA__" in filters

    def test_github_space_key_filter(self):
        result = classify_intent("What PRs were merged in the github repo recently?")
        filters = result.space_key_filters
        assert filters is None or "__GITHUB__" in filters

    def test_generic_no_filter(self):
        result = classify_intent("How does the API work?")
        assert result.space_key_filters is None


class TestIntentResult:
    def test_all_sources_no_filter(self):
        result = IntentResult(sources=ALL_SOURCES, confidence=0.3, matched_source=None)
        assert result.space_key_filters is None

    def test_jira_only_filter(self):
        result = IntentResult(sources=[SOURCE_JIRA], confidence=0.8, matched_source=SOURCE_JIRA)
        assert result.space_key_filters == ["__JIRA__"]

    def test_github_only_filter(self):
        result = IntentResult(sources=[SOURCE_GITHUB], confidence=0.8, matched_source=SOURCE_GITHUB)
        assert result.space_key_filters == ["__GITHUB__"]

    def test_confluence_only_no_filter(self):
        result = IntentResult(sources=[SOURCE_CONFLUENCE], confidence=0.8, matched_source=SOURCE_CONFLUENCE)
        # Confluence uses dynamic space keys, so no filter
        assert result.space_key_filters is None
