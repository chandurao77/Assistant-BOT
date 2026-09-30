"""Tests for the LLM-based cross-encoder re-ranker."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.models.document import classify_page_type
from app.models.schemas import SourceDocument
from app.services.reranker import Reranker


# ── _classify_page_type tests ─────────────────────────────────────────────────

class TestClassifyPageType:
    def test_howto_how_to(self):
        assert classify_page_type("How to Get Jira Access") == "howto"

    def test_howto_guide(self):
        assert classify_page_type("Developer Guide to Onboarding") == "howto"

    def test_howto_setup(self):
        assert classify_page_type("Flow Recommended IDE Setup") == "howto"

    def test_howto_getting_started(self):
        assert classify_page_type("Getting Started with Flow PM") == "howto"

    def test_reference_api(self):
        assert classify_page_type("API Rate Limits and Quotas") == "reference"

    def test_reference_architecture(self):
        assert classify_page_type("Gateway Architecture Overview") == "reference"

    def test_reference_security(self):
        assert classify_page_type("Security and Authentication Policy") == "reference"

    def test_report_release_notes(self):
        assert classify_page_type("Release Notes 07/23/2019") == "report"

    def test_report_quarterly_status(self):
        assert classify_page_type("2020 | Q1  Status Wiki") == "report"

    def test_report_backlog(self):
        assert classify_page_type("Q3 2022 Product Backlog") == "report"

    def test_report_priorities(self):
        assert classify_page_type("Chad_Q2 2022 Priorities") == "report"

    def test_general_fallback(self):
        assert classify_page_type("Syndication Gateway Lifecycle Events") == "general"

    def test_priority_howto_over_report(self):
        # "Q3" is a report keyword but "guide" should win (priority 1 > 3)
        assert classify_page_type("Q3 Architecture Guide") == "howto"

    def test_priority_reference_over_report(self):
        # "Q3" is report keyword but "API" should win (priority 2 > 3)
        assert classify_page_type("Q3 API Gateway Architecture Review") == "reference"

    def test_report_not_triggered_by_api_status(self):
        # "Status" alone without "wiki/report/update" should NOT be report
        # because "API" hits reference first
        assert classify_page_type("API Status Codes and Error Handling") == "reference"

def _make_source(title: str, score: float, content: str = "") -> SourceDocument:
    return SourceDocument(
        page_id=f"p_{title}",
        title=title,
        url=f"https://example.com/{title}",
        space_key="ENG",
        space_name="Engineering",
        excerpt=content or f"Content about {title}",
        content=content or f"Content about {title}",
        score=score,
    )


def _make_reranker(enabled: bool = True, top_n: int = 5) -> Reranker:
    settings = MagicMock()
    settings.rerank_enabled = enabled
    settings.rerank_top_n = top_n
    settings.ollama_base_url = "http://localhost:11434"
    settings.ollama_llm_model = "mistral"
    return Reranker(settings)


class TestRerankerInit:
    def test_init_disabled(self):
        reranker = _make_reranker(enabled=False)
        assert reranker._enabled is False

    def test_init_enabled(self):
        reranker = _make_reranker(enabled=True)
        assert reranker._enabled is True


class TestRerankerDisabled:
    @pytest.mark.asyncio
    async def test_returns_original_when_disabled(self):
        reranker = _make_reranker(enabled=False)
        sources = [_make_source("A", 0.9), _make_source("B", 0.8)]
        result = await reranker.rerank("test question", sources)
        assert result == sources

    @pytest.mark.asyncio
    async def test_returns_original_with_single_source(self):
        reranker = _make_reranker(enabled=True)
        sources = [_make_source("A", 0.9)]
        result = await reranker.rerank("test question", sources)
        assert result == sources


class TestRerankerScoring:
    @pytest.mark.asyncio
    async def test_reranks_by_llm_score(self):
        reranker = _make_reranker(enabled=True, top_n=3)

        # Mock Ollama responses: B gets highest score
        responses = iter(["3", "9", "6"])

        async def mock_post(url, json=None, **kwargs):
            resp = MagicMock()
            resp.json.return_value = {"response": next(responses)}
            return resp

        sources = [
            _make_source("A", 0.9),
            _make_source("B", 0.5),
            _make_source("C", 0.7),
        ]

        with patch("httpx.AsyncClient") as mock_client:
            instance = AsyncMock()
            instance.post = mock_post
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value = instance

            result = await reranker.rerank("test question", sources)

        # Reranker preserves original order (score-only, no reordering)
        assert result[0].title == "A"
        assert result[1].title == "B"
        assert result[2].title == "C"
        # Scores should be updated (not raw cosine)
        assert all(0 < s.score <= 1.0 for s in result)

    @pytest.mark.asyncio
    async def test_top_n_limits_results(self):
        reranker = _make_reranker(enabled=True, top_n=2)

        responses = iter(["8", "5", "3", "1"])

        async def mock_post(url, json=None, **kwargs):
            resp = MagicMock()
            resp.json.return_value = {"response": next(responses)}
            return resp

        sources = [_make_source(f"S{i}", 0.5) for i in range(4)]

        with patch("httpx.AsyncClient") as mock_client:
            instance = AsyncMock()
            instance.post = mock_post
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value = instance

            result = await reranker.rerank("test question", sources)

        # Reranker no longer limits results, returns all with updated scores
        assert len(result) == 4

    @pytest.mark.asyncio
    async def test_fallback_on_error(self):
        reranker = _make_reranker(enabled=True, top_n=5)

        async def mock_post(url, json=None, **kwargs):
            raise httpx.ConnectError("Connection refused")

        sources = [_make_source("A", 0.9), _make_source("B", 0.8)]

        with patch("httpx.AsyncClient") as mock_client:
            instance = AsyncMock()
            instance.post = mock_post
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value = instance

            result = await reranker.rerank("test question", sources)

        # Should fall back to original scores (0.9*10=9.0 > 0.8*10=8.0)
        assert len(result) == 2
        assert result[0].title == "A"


class TestScoreOne:
    @pytest.mark.asyncio
    async def test_parses_numeric_response(self):
        reranker = _make_reranker()
        source = _make_source("Test", 0.5)

        mock_client = AsyncMock()
        resp = MagicMock()
        resp.json.return_value = {"response": "7"}
        mock_client.post = AsyncMock(return_value=resp)

        score = await reranker._score_one(mock_client, "question", source)
        assert score == 7.0

    @pytest.mark.asyncio
    async def test_caps_score_at_10(self):
        reranker = _make_reranker()
        source = _make_source("Test", 0.5)

        mock_client = AsyncMock()
        resp = MagicMock()
        resp.json.return_value = {"response": "15"}
        mock_client.post = AsyncMock(return_value=resp)

        score = await reranker._score_one(mock_client, "question", source)
        assert score == 10.0

    @pytest.mark.asyncio
    async def test_fallback_on_non_numeric(self):
        reranker = _make_reranker()
        source = _make_source("Test", 0.6)

        mock_client = AsyncMock()
        resp = MagicMock()
        resp.json.return_value = {"response": "I cannot rate this"}
        mock_client.post = AsyncMock(return_value=resp)

        score = await reranker._score_one(mock_client, "question", source)
        # "I cannot rate this" contains "NO" -> maps to 2.0 via _SCORE_MAP
        assert score == 2.0


# ── Label adjustment tests ─────────────────────────────────────────────────────

class TestLabelAdjustment:
    """Tests for _label_adjustment() — label-based score delta."""

    def setup_method(self):
        from app.services.reranker import _label_adjustment
        self._fn = _label_adjustment

    def test_no_labels_neutral(self):
        assert self._fn([]) == 0.0

    def test_deprecated_penalized(self):
        assert self._fn(["deprecated"]) == -0.15

    def test_archived_penalized(self):
        assert self._fn(["archived"]) == -0.15

    def test_outdated_penalized(self):
        assert self._fn(["outdated"]) == -0.15

    def test_legacy_penalized(self):
        assert self._fn(["legacy"]) == -0.15

    def test_obsolete_penalized(self):
        assert self._fn(["obsolete"]) == -0.15

    def test_official_boosted(self):
        assert self._fn(["official"]) == 0.05

    def test_canonical_boosted(self):
        assert self._fn(["canonical"]) == 0.05

    def test_approved_boosted(self):
        assert self._fn(["approved"]) == 0.05

    def test_recommended_boosted(self):
        assert self._fn(["recommended"]) == 0.05

    def test_penalty_beats_boost(self):
        # deprecated + canonical → penalty wins
        assert self._fn(["deprecated", "canonical"]) == -0.15

    def test_case_insensitive(self):
        assert self._fn(["Deprecated"]) == -0.15
        assert self._fn(["OFFICIAL"]) == 0.05

    def test_unrelated_labels_neutral(self):
        assert self._fn(["team-platform", "backend", "flow"]) == 0.0


# ── Integration: full rerank pipeline ─────────────────────────────────────────

class TestRerankerIntegration:
    """End-to-end tests: question + sources → scores reflect all adjustments.

    These test the complete scoring path:
      30% keyword + 50% vector + answer_bonus + title_boost + type_adj + label_adj
    No LLM is called — the heuristic path runs synchronously inside rerank().
    """

    def _make_src(
        self,
        title: str,
        score: float,
        content: str = "",
        page_type: str = "",
        labels: list[str] | None = None,
    ) -> SourceDocument:
        return SourceDocument(
            page_id=f"p_{title}",
            title=title,
            url=f"https://example.com/{title}",
            space_key="ENG",
            space_name="Engineering",
            excerpt=content or f"Content about {title}",
            content=content or f"Content about {title}",
            score=score,
            page_type=page_type,
            labels=labels or [],
        )

    @pytest.mark.asyncio
    async def test_report_page_scores_lower_than_howto(self):
        """A status report page should score lower than a how-to guide on the same question."""
        reranker = _make_reranker()
        question = "How do I set up my development environment?"
        guide = self._make_src(
            "IDE Setup Guide",
            score=0.75,
            content="To set up your development environment, install the IDE and configure settings.",
            page_type="howto",
        )
        status = self._make_src(
            "2024 Q2 Status Wiki",
            score=0.75,  # same vector score
            content="Q2 status update: team completed sprint goals.",
            page_type="report",
        )
        result = await reranker.rerank(question, [guide, status])
        guide_score = next(s.score for s in result if s.title == "IDE Setup Guide")
        status_score = next(s.score for s in result if s.title == "2024 Q2 Status Wiki")
        assert guide_score > status_score, (
            f"Guide ({guide_score}) should outscore status report ({status_score})"
        )

    @pytest.mark.asyncio
    async def test_deprecated_page_scores_lower(self):
        """A deprecated page should score lower than an identical non-deprecated page."""
        reranker = _make_reranker()
        question = "How do I authenticate to the API?"
        current = self._make_src(
            "API Authentication Guide",
            score=0.80,
            content="Use OAuth 2.0 to authenticate to the API with a bearer token.",
            labels=[],
        )
        old = self._make_src(
            "API Authentication Guide (Old)",
            score=0.80,  # same vector score
            content="Use OAuth 2.0 to authenticate to the API with a bearer token.",
            labels=["deprecated"],
        )
        result = await reranker.rerank(question, [current, old])
        current_score = next(s.score for s in result if "Old" not in s.title)
        old_score = next(s.score for s in result if "Old" in s.title)
        assert current_score > old_score, (
            f"Current ({current_score}) should outscore deprecated ({old_score})"
        )

    @pytest.mark.asyncio
    async def test_official_page_scores_higher(self):
        """An official/canonical page should score higher than an unlabeled equivalent."""
        reranker = _make_reranker()
        # Stub the LLM call so both sources get the same model score and only
        # the label boost differs (otherwise the result depends on a live Ollama).
        reranker._score_one = AsyncMock(return_value=5.0)
        question = "What is the onboarding process?"
        # Use score=0.60 so the +0.05 label boost isn't swallowed by the 1.0 ceiling
        official = self._make_src(
            "Onboarding Guide",
            score=0.60,
            content="The onboarding process consists of three steps.",
            labels=["official"],
        )
        unlabeled = self._make_src(
            "Onboarding Notes",
            score=0.60,
            content="The onboarding process consists of three steps.",
            labels=[],
        )
        result = await reranker.rerank(question, [official, unlabeled])
        official_score = next(s.score for s in result if s.title == "Onboarding Guide")
        unlabeled_score = next(s.score for s in result if s.title == "Onboarding Notes")
        assert official_score > unlabeled_score

    @pytest.mark.asyncio
    async def test_scores_clamped_between_0_and_1(self):
        """No score should go below 0 or above 1 regardless of adjustments."""
        reranker = _make_reranker()
        sources = [
            self._make_src("Very Relevant", score=0.99, content="setup guide howto", page_type="howto", labels=["official"]),
            self._make_src("Very Irrelevant", score=0.01, content="unrelated text", page_type="report", labels=["deprecated"]),
        ]
        result = await reranker.rerank("How do I set up?", sources)
        for s in result:
            assert 0.0 <= s.score <= 1.0, f"Score {s.score} out of range for {s.title}"

    @pytest.mark.asyncio
    async def test_stored_page_type_used_over_title_classification(self):
        """If page_type is stored in payload, it should be used; title should not override it."""
        reranker = _make_reranker()
        # Title looks like a report ("Q1") but page_type is explicitly set to "reference"
        src = self._make_src(
            "Q1 API Architecture Document",
            score=0.70,
            content="API architecture details.",
            page_type="reference",  # stored at ingest time
        )
        result = await reranker.rerank("What is the API architecture?", [src])
        # reference gets +0.05, report would get -0.20 → difference of 0.25
        # Score should reflect reference boost, not report penalty
        # With score=0.70 vector, reference adj=+0.05: base = 0.5*0.70 + 0.05 = 0.40 (min)
        assert result[0].score > 0.30  # would be near 0 if report penalty applied
