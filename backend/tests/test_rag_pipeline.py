"""Unit tests for app.services.rag — RAG pipeline (all dependencies mocked)."""
from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.models.schemas import SourceDocument
from app.services.rag import RAGPipeline, _NO_CONTEXT_REPLY


def _make_settings():
    s = MagicMock()
    s.retrieval_top_k = 3
    s.retrieval_score_threshold = 0.35
    s.max_context_words_per_source = 400
    s.graph_hop_depth = 0
    s.graph_max_expansion = 4
    s.llm_max_sources = 5
    s.semantic_cache_enabled = True
    s.semantic_cache_threshold = 0.95
    s.semantic_cache_ttl = 1800
    s.content_guardrail_enabled = True
    s.entity_extraction_enabled = False
    s.rerank_enabled = False
    s.rerank_top_n = 5
    return s


def _make_source(page_id: str = "p1", score: float = 0.8) -> SourceDocument:
    return SourceDocument(
        page_id=page_id,
        title=f"Page {page_id}",
        url=f"https://example.com/{page_id}",
        space_key="ENG",
        space_name="Engineering",
        excerpt="Short excerpt text.",
        content="Full content text that is longer than the excerpt and contains all details.",
        score=score,
    )


@pytest.fixture
def pipeline():
    with (
        patch("app.services.rag.EmbeddingService") as MockEmbed,
        patch("app.services.rag.VectorStore") as MockVS,
        patch("app.services.rag.LLMService") as MockLLM,
        patch("app.services.rag.SemanticCache") as MockCache,
        patch("app.services.rag.ContentGuardrail") as MockGuardrail,
        patch("app.services.rag.Reranker") as MockReranker,
        patch("app.services.rag.needs_rewrite", return_value=False),
        patch("app.services.rag.rewrite_query", new_callable=AsyncMock, return_value=None),
    ):
        mock_embed = AsyncMock()
        mock_embed.embed.return_value = [0.1] * 768
        MockEmbed.return_value = mock_embed

        mock_vs = AsyncMock()
        MockVS.return_value = mock_vs

        mock_llm = MagicMock()
        MockLLM.return_value = mock_llm

        mock_cache = AsyncMock()
        mock_cache.lookup.return_value = None  # default: cache miss
        mock_cache.enabled = True
        MockCache.return_value = mock_cache

        mock_guardrail = MagicMock()
        mock_guardrail.redact_chunks.side_effect = lambda chunks: (chunks, 0)
        mock_guardrail.redact_output.side_effect = lambda text: text
        mock_guardrail.enabled = True
        MockGuardrail.return_value = mock_guardrail

        mock_reranker = AsyncMock()
        mock_reranker.rerank.side_effect = lambda q, sources: sources
        MockReranker.return_value = mock_reranker

        p = RAGPipeline(_make_settings())
        p._mock_embed = mock_embed
        p._mock_vs = mock_vs
        p._mock_llm = mock_llm
        p._mock_cache = mock_cache
        p._mock_guardrail = mock_guardrail
        p._mock_reranker = mock_reranker
        yield p


class TestRAGPipelineStream:
    @pytest.mark.asyncio
    async def test_no_sources_yields_refusal(self, pipeline):
        pipeline._mock_vs.search.return_value = []
        tokens = []
        sources_received = []
        async for token, sources in pipeline.stream("What is X?"):
            if sources is not None:
                sources_received.append(sources)
            else:
                tokens.append(token)

        full_text = "".join(tokens)
        assert _NO_CONTEXT_REPLY in full_text
        assert sources_received == [[]]  # empty sources list emitted

    @pytest.mark.asyncio
    async def test_streams_tokens_when_sources_found(self, pipeline):
        pipeline._mock_vs.search.return_value = [_make_source("p1")]

        async def _fake_stream(question, context, **kwargs):
            for word in ["The", " answer", " is", " here"]:
                yield word

        pipeline._mock_llm.stream_answer = _fake_stream

        tokens = []
        async for token, sources in pipeline.stream("What is X?"):
            if sources is None:
                tokens.append(token)

        assert tokens == ["The", " answer", " is", " here"]

    @pytest.mark.asyncio
    async def test_emits_sources_after_tokens(self, pipeline):
        src = _make_source("p1", score=0.9)
        pipeline._mock_vs.search.return_value = [src]

        async def _fake_stream(question, context, **kwargs):
            yield "Answer"

        pipeline._mock_llm.stream_answer = _fake_stream

        final_sources = None
        async for token, sources in pipeline.stream("Question?"):
            if sources is not None:
                final_sources = sources

        assert final_sources is not None
        assert len(final_sources) == 1
        assert final_sources[0].page_id == "p1"

    @pytest.mark.asyncio
    async def test_context_uses_full_content_not_excerpt(self, pipeline):
        src = _make_source("p1")
        pipeline._mock_vs.search.return_value = [src]

        captured_context = []

        async def _capture_stream(question, context, **kwargs):
            captured_context.extend(context)
            yield "ok"

        pipeline._mock_llm.stream_answer = _capture_stream

        async for _ in pipeline.stream("Question?"):
            pass

        assert len(captured_context) == 1
        # Should use content (full text), not excerpt
        assert captured_context[0]["text"] != "Short excerpt text."
        assert "Full content text" in captured_context[0]["text"]

    @pytest.mark.asyncio
    async def test_context_words_capped_at_400(self, pipeline):
        src = _make_source("p1")
        src.content = " ".join(["word"] * 600)  # 600-word content
        pipeline._mock_vs.search.return_value = [src]

        captured_context = []

        async def _capture_stream(question, context, **kwargs):
            captured_context.extend(context)
            yield "ok"

        pipeline._mock_llm.stream_answer = _capture_stream

        async for _ in pipeline.stream("Question?"):
            pass

        word_count = len(captured_context[0]["text"].split())
        assert word_count <= 400

    @pytest.mark.asyncio
    async def test_embeds_question_before_search(self, pipeline):
        pipeline._mock_vs.search.return_value = []
        async for _ in pipeline.stream("My question"):
            pass
        pipeline._mock_embed.embed.assert_called_once_with("My question")

    @pytest.mark.asyncio
    async def test_search_called_with_correct_params(self, pipeline):
        pipeline._mock_vs.search.return_value = []
        async for _ in pipeline.stream("Q", space_keys=["ENG"]):
            pass
        pipeline._mock_vs.search.assert_called_once_with(
            query_vector=[0.1] * 768,
            top_k=3,
            score_threshold=0.35,
            space_keys=["ENG"],
            query_text="Q",
        )


class TestGraphExpansion:
    @pytest.mark.asyncio
    async def test_graph_expansion_adds_linked_pages(self, pipeline):
        """When graph_hop_depth > 0 and conversation_store has links, extra sources are added."""
        pipeline._settings.graph_hop_depth = 1
        primary_src = _make_source("p1")
        linked_src = _make_source("p2", score=0.0)

        pipeline._mock_vs.search.return_value = [primary_src]
        pipeline._mock_vs.fetch_by_page_ids = AsyncMock(return_value=[linked_src])

        mock_store = AsyncMock()
        mock_store.get_linked_page_ids = AsyncMock(return_value=["p2"])

        async def _fake_stream(question, context, **kwargs):
            yield "ok"

        pipeline._mock_llm.stream_answer = _fake_stream

        final_sources = None
        async for _, sources in pipeline.stream("Q?", conversation_store=mock_store):
            if sources is not None:
                final_sources = sources

        assert final_sources is not None
        page_ids = [s.page_id for s in final_sources]
        assert "p1" in page_ids
        assert "p2" in page_ids

    @pytest.mark.asyncio
    async def test_graph_expansion_skipped_when_depth_zero(self, pipeline):
        """graph_hop_depth=0 means no expansion — conversation_store is not queried."""
        pipeline._settings.graph_hop_depth = 0
        pipeline._mock_vs.search.return_value = [_make_source("p1")]

        mock_store = AsyncMock()
        mock_store.get_linked_page_ids = AsyncMock(return_value=["p2"])

        async def _fake_stream(question, context, **kwargs):
            yield "ok"

        pipeline._mock_llm.stream_answer = _fake_stream

        async for _ in pipeline.stream("Q?", conversation_store=mock_store):
            pass

        mock_store.get_linked_page_ids.assert_not_called()

    @pytest.mark.asyncio
    async def test_graph_expansion_skipped_without_store(self, pipeline):
        """No conversation_store passed — expansion is silently skipped."""
        pipeline._settings.graph_hop_depth = 1
        pipeline._mock_vs.search.return_value = [_make_source("p1")]
        pipeline._mock_vs.fetch_by_page_ids = AsyncMock(return_value=[])

        async def _fake_stream(question, context, **kwargs):
            yield "ok"

        pipeline._mock_llm.stream_answer = _fake_stream

        final_sources = None
        async for _, sources in pipeline.stream("Q?"):  # no conversation_store
            if sources is not None:
                final_sources = sources

        assert final_sources is not None
        pipeline._mock_vs.fetch_by_page_ids.assert_not_called()


class TestNegativeAnswerCacheSkip:
    """Negative/no-answer LLM responses must NOT be cached."""

    @pytest.mark.asyncio
    async def test_negative_answer_not_cached(self, pipeline):
        """When the LLM says 'I don't have enough information', cache.store is not called."""
        pipeline._mock_vs.search.return_value = [_make_source("p1")]

        async def _negative_stream(question, context, **kwargs):
            yield "I don't have enough information to answer that question."

        pipeline._mock_llm.stream_answer = _negative_stream

        async for _ in pipeline.stream("What is Assistant Bot?"):
            pass

        pipeline._mock_cache.store.assert_not_called()

    @pytest.mark.asyncio
    async def test_positive_answer_is_cached(self, pipeline):
        """Normal answers should be cached as before."""
        pipeline._mock_vs.search.return_value = [_make_source("p1")]

        async def _positive_stream(question, context, **kwargs):
            yield "Assistant Bot is a knowledge assistant."

        pipeline._mock_llm.stream_answer = _positive_stream

        async for _ in pipeline.stream("What is Assistant Bot?"):
            pass

        pipeline._mock_cache.store.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_sources_refusal_not_cached(self, pipeline):
        """When zero sources are found the refusal is returned but never cached."""
        pipeline._mock_vs.search.return_value = []

        async for _ in pipeline.stream("Unknown topic?"):
            pass

        pipeline._mock_cache.store.assert_not_called()
