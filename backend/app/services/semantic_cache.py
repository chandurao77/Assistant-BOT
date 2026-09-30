"""
Semantic cache for RAG pipeline responses.

Uses a dedicated Qdrant collection to store question embeddings alongside
their cached LLM answers.  When a new question arrives, we search this
collection — if a semantically similar question is found above a
configurable similarity threshold, the cached answer (+ sources) is
returned immediately, skipping the full RAG pipeline.

When Redis is enabled, an exact-match layer (keyed by normalised question
hash) is checked first — cache hits from Redis skip the Qdrant vector
search entirely.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from typing import TYPE_CHECKING

from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models as qmodels

from app.config import Settings
from app.models.schemas import SourceDocument

if TYPE_CHECKING:
    from app.services.redis_cache import RedisCache

logger = logging.getLogger(__name__)

_COLLECTION = "semantic_cache"


class SemanticCache:
    """Qdrant-backed semantic cache for RAG answers, with optional Redis L1 layer."""

    # Class-level counters for cache hit rate tracking
    _hits: int = 0
    _misses: int = 0

    def __init__(self, settings: Settings, redis_cache: "RedisCache | None" = None) -> None:
        self._client = AsyncQdrantClient(
            host=settings.qdrant_host,
            port=settings.qdrant_port,
            prefer_grpc=False,
        )
        self._vector_size = settings.qdrant_vector_size
        self._threshold = settings.semantic_cache_threshold
        self._ttl = settings.semantic_cache_ttl
        self._enabled = settings.semantic_cache_enabled
        self._redis = redis_cache

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def ensure_collection(self) -> None:
        """Create the cache collection if it doesn't already exist."""
        if not self._enabled:
            return
        collections = await self._client.get_collections()
        names = [c.name for c in collections.collections]
        if _COLLECTION not in names:
            await self._client.create_collection(
                collection_name=_COLLECTION,
                vectors_config=qmodels.VectorParams(
                    size=self._vector_size,
                    distance=qmodels.Distance.COSINE,
                ),
            )
            logger.info("Created semantic cache collection '%s'", _COLLECTION)

    async def lookup(
        self, query_vector: list[float], question: str = ""
    ) -> tuple[str, list[SourceDocument]] | None:
        """
        Search for a semantically similar cached question.

        Returns ``(cached_answer, cached_sources)`` on a hit, or ``None`` on a miss.
        Expired entries (older than TTL) are treated as misses.
        """
        if not self._enabled:
            return None

        # L1: Redis exact-match (by normalised question hash)
        if question and self._redis and self._redis.available:
            qhash = self._question_hash(question)
            cached = await self._redis.get_qa(qhash)
            if cached:
                cached_at = cached.get("cached_at", 0)
                if time.time() - cached_at <= self._ttl:
                    sources = [SourceDocument(**s) for s in json.loads(cached.get("sources", "[]"))]
                    logger.info("Semantic cache HIT (Redis exact, question=%r)", question[:60])
                    SemanticCache._hits += 1
                    return cached["answer"], sources

        # L2: Qdrant vector similarity search

        try:
            results = await self._client.search(
                collection_name=_COLLECTION,
                query_vector=query_vector,
                limit=1,
                score_threshold=self._threshold,
            )
        except Exception:
            logger.debug("Semantic cache lookup failed (collection may not exist), treating as MISS")
            SemanticCache._misses += 1
            return None
        if not results:
            SemanticCache._misses += 1
            return None

        hit = results[0]
        payload = hit.payload or {}

        # Check TTL
        cached_at = payload.get("cached_at", 0)
        if time.time() - cached_at > self._ttl:
            # Expired — delete the stale entry
            await self._client.delete(
                collection_name=_COLLECTION,
                points_selector=qmodels.PointIdsList(points=[hit.id]),
            )
            logger.debug("Evicted expired cache entry (age=%ds)", int(time.time() - cached_at))
            return None

        answer = payload.get("answer", "")
        sources_raw = payload.get("sources", "[]")
        sources = [SourceDocument(**s) for s in json.loads(sources_raw)]

        logger.info(
            "Semantic cache HIT (score=%.3f, question=%r)",
            hit.score,
            payload.get("question", "")[:60],
        )
        SemanticCache._hits += 1
        return answer, sources

    async def store(
        self,
        question: str,
        query_vector: list[float],
        answer: str,
        sources: list[SourceDocument],
    ) -> None:
        """Cache a question/answer pair for future semantic lookup."""
        if not self._enabled:
            return

        sources_json = json.dumps([s.model_dump() for s in sources])
        now = time.time()

        # Write to Redis (exact-match layer)
        if self._redis and self._redis.available:
            qhash = self._question_hash(question)
            await self._redis.set_qa(qhash, {
                "question": question,
                "answer": answer,
                "sources": sources_json,
                "cached_at": now,
            }, ttl=self._ttl)

        # Write to Qdrant (vector similarity layer)
        point = qmodels.PointStruct(
            id=str(uuid.uuid4()),
            vector=query_vector,
            payload={
                "question": question,
                "answer": answer,
                "sources": sources_json,
                "cached_at": now,
            },
        )
        try:
            await self._client.upsert(
                collection_name=_COLLECTION,
                points=[point],
                wait=True,
            )
            logger.debug("Cached answer for question: %r", question[:60])
        except Exception:
            logger.debug("Semantic cache store failed (collection may not exist), skipping")

    async def invalidate(self) -> None:
        """
        Clear all cached entries.  Call after re-ingestion to avoid stale answers.
        """
        if not self._enabled:
            return

        # Clear Redis Q&A cache
        if self._redis and self._redis.available:
            await self._redis.invalidate_qa()

        # Clear Qdrant cache collection
        collections = await self._client.get_collections()
        names = [c.name for c in collections.collections]
        if _COLLECTION in names:
            await self._client.delete_collection(_COLLECTION)
            await self.ensure_collection()
            logger.info("Semantic cache invalidated (collection recreated)")

    @staticmethod
    def _question_hash(question: str) -> str:
        """Deterministic hash of a normalised question for Redis key."""
        normalised = " ".join(question.lower().strip().split())
        return hashlib.sha256(normalised.encode()).hexdigest()

    @classmethod
    def get_stats(cls) -> dict:
        """Return cache hit/miss statistics."""
        total = cls._hits + cls._misses
        return {
            "hits": cls._hits,
            "misses": cls._misses,
            "total_lookups": total,
            "hit_rate": round(cls._hits / total, 4) if total else 0.0,
        }

    async def cleanup_expired(self) -> int:
        """Delete all cache entries older than TTL. Returns count of evicted entries."""
        if not self._enabled:
            return 0
        cutoff = time.time() - self._ttl
        evicted = 0
        offset = None
        while True:
            results, next_offset = await self._client.scroll(
                collection_name=_COLLECTION,
                scroll_filter=qmodels.Filter(
                    must=[
                        qmodels.FieldCondition(
                            key="cached_at",
                            range=qmodels.Range(lt=cutoff),
                        )
                    ]
                ),
                limit=100,
                offset=offset,
                with_payload=False,
                with_vectors=False,
            )
            if not results:
                break
            ids = [r.id for r in results]
            await self._client.delete(
                collection_name=_COLLECTION,
                points_selector=qmodels.PointIdsList(points=ids),
            )
            evicted += len(ids)
            if next_offset is None:
                break
            offset = next_offset
        if evicted:
            logger.info("Semantic cache cleanup: evicted %d expired entries", evicted)
        return evicted
