"""Unit tests for app.services.vector_store (Qdrant client mocked)."""
from __future__ import annotations
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from app.models.document import DocumentChunk
from app.models.schemas import SourceDocument
from app.services.vector_store import VectorStore


def _make_settings():
    s = MagicMock()
    s.qdrant_host = "localhost"
    s.qdrant_port = 6333
    s.qdrant_collection = "test_collection"
    s.qdrant_vector_size = 768
    return s


def _make_chunk(page_id: str = "p1", idx: int = 0) -> DocumentChunk:
    return DocumentChunk(
        chunk_id=f"{page_id}_{idx}",
        page_id=page_id,
        title="Test Page",
        space_key="ENG",
        space_name="Engineering",
        url="https://example.com/page",
        text="This is test content for the chunk.",
        chunk_index=idx,
        total_chunks=1,
        last_modified=datetime.now(timezone.utc),
    )


def _make_hit(page_id: str, score: float, text: str = "chunk text") -> MagicMock:
    hit = MagicMock()
    hit.score = score
    hit.payload = {
        "page_id": page_id,
        "title": f"Page {page_id}",
        "url": f"https://example.com/{page_id}",
        "space_key": "ENG",
        "space_name": "Engineering",
        "text": text,
    }
    return hit


@pytest.fixture
def mock_qdrant():
    with patch("app.services.vector_store.AsyncQdrantClient") as MockClient:
        client = AsyncMock()
        MockClient.return_value = client
        yield client


@pytest.fixture
def store(mock_qdrant):
    return VectorStore(_make_settings())


class TestEnsureCollection:
    @pytest.mark.asyncio
    async def test_creates_collection_if_not_exists(self, store, mock_qdrant):
        mock_qdrant.get_collections.return_value = MagicMock(collections=[])
        await store.ensure_collection()
        mock_qdrant.create_collection.assert_called_once()

    @pytest.mark.asyncio
    async def test_skips_creation_if_exists(self, store, mock_qdrant):
        existing = MagicMock()
        existing.name = "test_collection"
        mock_qdrant.get_collections.return_value = MagicMock(collections=[existing])
        await store.ensure_collection()
        mock_qdrant.create_collection.assert_not_called()

    @pytest.mark.asyncio
    async def test_drops_and_recreates_on_full_refresh(self, store, mock_qdrant):
        existing = MagicMock()
        existing.name = "test_collection"
        mock_qdrant.get_collections.return_value = MagicMock(collections=[existing])
        await store.ensure_collection(drop_existing=True)
        mock_qdrant.delete_collection.assert_called_once_with("test_collection")
        mock_qdrant.create_collection.assert_called_once()


class TestUpsertChunks:
    @pytest.mark.asyncio
    async def test_upserts_points(self, store, mock_qdrant):
        chunks = [_make_chunk("p1", 0), _make_chunk("p1", 1)]
        vectors = [[0.1] * 768, [0.2] * 768]
        await store.upsert_chunks(chunks, vectors)
        mock_qdrant.upsert.assert_called_once()

    @pytest.mark.asyncio
    async def test_empty_chunks_no_upsert(self, store, mock_qdrant):
        await store.upsert_chunks([], [])
        mock_qdrant.upsert.assert_not_called()

    @pytest.mark.asyncio
    async def test_batches_large_upserts(self, store, mock_qdrant):
        # 250 chunks should be split into 3 batches of 100/100/50
        chunks = [_make_chunk("p1", i) for i in range(250)]
        vectors = [[0.1] * 768] * 250
        await store.upsert_chunks(chunks, vectors)
        assert mock_qdrant.upsert.call_count == 3


class TestSearch:
    @pytest.mark.asyncio
    async def test_returns_source_documents(self, store, mock_qdrant):
        mock_qdrant.search.return_value = [
            _make_hit("p1", 0.9, "full text content"),
            _make_hit("p2", 0.7, "other content"),
        ]
        results = await store.search(query_vector=[0.1] * 768)
        assert len(results) == 2
        assert all(isinstance(r, SourceDocument) for r in results)

    @pytest.mark.asyncio
    async def test_deduplicates_by_page_id(self, store, mock_qdrant):
        # Two hits for same page — only highest score kept
        mock_qdrant.search.return_value = [
            _make_hit("p1", 0.9),
            _make_hit("p1", 0.6),
        ]
        results = await store.search(query_vector=[0.1] * 768)
        assert len(results) == 1
        assert results[0].score == 0.9

    @pytest.mark.asyncio
    async def test_excerpt_truncated_to_500(self, store, mock_qdrant):
        long_text = "word " * 300  # 1500 chars
        mock_qdrant.search.return_value = [_make_hit("p1", 0.8, long_text)]
        results = await store.search(query_vector=[0.1] * 768)
        assert len(results[0].excerpt) <= 500

    @pytest.mark.asyncio
    async def test_content_field_is_full_text(self, store, mock_qdrant):
        long_text = "word " * 300
        mock_qdrant.search.return_value = [_make_hit("p1", 0.8, long_text)]
        results = await store.search(query_vector=[0.1] * 768)
        assert results[0].content == long_text

    @pytest.mark.asyncio
    async def test_space_filter_applied_when_provided(self, store, mock_qdrant):
        mock_qdrant.search.return_value = []
        await store.search(query_vector=[0.1] * 768, space_keys=["ENG"])
        call_kwargs = mock_qdrant.search.call_args.kwargs
        assert call_kwargs["query_filter"] is not None

    @pytest.mark.asyncio
    async def test_no_filter_when_no_space_keys(self, store, mock_qdrant):
        mock_qdrant.search.return_value = []
        await store.search(query_vector=[0.1] * 768, space_keys=None)
        call_kwargs = mock_qdrant.search.call_args.kwargs
        assert call_kwargs["query_filter"] is None


class TestHealth:
    @pytest.mark.asyncio
    async def test_returns_true_when_qdrant_ok(self, store, mock_qdrant):
        mock_qdrant.get_collections.return_value = MagicMock(collections=[])
        assert await store.health() is True

    @pytest.mark.asyncio
    async def test_returns_false_on_exception(self, store, mock_qdrant):
        mock_qdrant.get_collections.side_effect = httpx.ConnectError("connection refused")
        assert await store.health() is False
