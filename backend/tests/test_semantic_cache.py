"""Unit tests for app.services.semantic_cache — Qdrant-backed semantic cache."""
from __future__ import annotations

import json
import time

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.models.schemas import SourceDocument
from app.services.semantic_cache import SemanticCache


def _make_settings(enabled: bool = True, threshold: float = 0.95, ttl: int = 1800):
    s = MagicMock()
    s.qdrant_host = "localhost"
    s.qdrant_port = 6333
    s.qdrant_vector_size = 768
    s.semantic_cache_enabled = enabled
    s.semantic_cache_threshold = threshold
    s.semantic_cache_ttl = ttl
    return s


def _make_source(page_id: str = "p1", score: float = 0.9) -> SourceDocument:
    return SourceDocument(
        page_id=page_id,
        title=f"Page {page_id}",
        url=f"https://example.com/{page_id}",
        space_key="ENG",
        space_name="Engineering",
        excerpt="Test excerpt.",
        content="Test content.",
        score=score,
    )


class TestSemanticCacheDisabled:
    """When semantic_cache_enabled=False, all operations are no-ops."""

    def test_enabled_property(self):
        cache = SemanticCache(_make_settings(enabled=False))
        assert cache.enabled is False

    @pytest.mark.asyncio
    async def test_lookup_returns_none_when_disabled(self):
        cache = SemanticCache(_make_settings(enabled=False))
        result = await cache.lookup([0.1] * 768)
        assert result is None

    @pytest.mark.asyncio
    async def test_store_is_noop_when_disabled(self):
        cache = SemanticCache(_make_settings(enabled=False))
        # Should not raise
        await cache.store("test?", [0.1] * 768, "answer", [_make_source()])

    @pytest.mark.asyncio
    async def test_invalidate_is_noop_when_disabled(self):
        cache = SemanticCache(_make_settings(enabled=False))
        await cache.invalidate()

    @pytest.mark.asyncio
    async def test_ensure_collection_is_noop_when_disabled(self):
        cache = SemanticCache(_make_settings(enabled=False))
        await cache.ensure_collection()


class TestSemanticCacheLookup:
    """Cache lookup behaviour with mocked Qdrant client."""

    @pytest.mark.asyncio
    async def test_cache_miss_returns_none(self):
        cache = SemanticCache(_make_settings())
        cache._client = AsyncMock()
        cache._client.search.return_value = []

        result = await cache.lookup([0.1] * 768)
        assert result is None

    @pytest.mark.asyncio
    async def test_cache_hit_returns_answer_and_sources(self):
        cache = SemanticCache(_make_settings())
        cache._client = AsyncMock()

        source = _make_source()
        hit = MagicMock()
        hit.id = "test-id"
        hit.score = 0.97
        hit.payload = {
            "question": "What is deployment?",
            "answer": "Deployment is done via Docker.",
            "sources": json.dumps([source.model_dump()]),
            "cached_at": time.time(),
        }
        cache._client.search.return_value = [hit]

        result = await cache.lookup([0.1] * 768)
        assert result is not None
        answer, sources = result
        assert answer == "Deployment is done via Docker."
        assert len(sources) == 1
        assert sources[0].page_id == "p1"

    @pytest.mark.asyncio
    async def test_expired_entry_returns_none_and_deletes(self):
        cache = SemanticCache(_make_settings(ttl=60))
        cache._client = AsyncMock()

        hit = MagicMock()
        hit.id = "old-id"
        hit.score = 0.98
        hit.payload = {
            "question": "old question",
            "answer": "old answer",
            "sources": "[]",
            "cached_at": time.time() - 120,  # expired (120s > 60s TTL)
        }
        cache._client.search.return_value = [hit]

        result = await cache.lookup([0.1] * 768)
        assert result is None
        # Verify deletion was called
        cache._client.delete.assert_called_once()


class TestSemanticCacheStore:
    @pytest.mark.asyncio
    async def test_store_upserts_to_qdrant(self):
        cache = SemanticCache(_make_settings())
        cache._client = AsyncMock()

        source = _make_source()
        await cache.store("test question", [0.1] * 768, "test answer", [source])

        cache._client.upsert.assert_called_once()
        call_kwargs = cache._client.upsert.call_args
        assert call_kwargs.kwargs["collection_name"] == "semantic_cache"
        point = call_kwargs.kwargs["points"][0]
        assert point.payload["question"] == "test question"
        assert point.payload["answer"] == "test answer"


class TestSemanticCacheInvalidate:
    @pytest.mark.asyncio
    async def test_invalidate_recreates_collection(self):
        cache = SemanticCache(_make_settings())
        cache._client = AsyncMock()

        # First call (invalidate): collection exists → delete it
        # Second call (ensure_collection): collection gone → create it
        coll_exists = MagicMock()
        coll = MagicMock()
        coll.name = "semantic_cache"
        coll_exists.collections = [coll]

        coll_empty = MagicMock()
        coll_empty.collections = []

        cache._client.get_collections.side_effect = [coll_exists, coll_empty]

        await cache.invalidate()

        cache._client.delete_collection.assert_called_once_with("semantic_cache")
        cache._client.create_collection.assert_called_once()

    @pytest.mark.asyncio
    async def test_invalidate_when_collection_missing(self):
        cache = SemanticCache(_make_settings())
        cache._client = AsyncMock()

        collections_resp = MagicMock()
        collections_resp.collections = []
        cache._client.get_collections.return_value = collections_resp

        await cache.invalidate()
        # Should not try to delete a non-existent collection
        cache._client.delete_collection.assert_not_called()
