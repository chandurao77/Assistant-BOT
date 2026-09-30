"""Embedding service backed by Ollama (nomic-embed-text)."""
from __future__ import annotations
import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any

import httpx
import pybreaker
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.config import Settings

# Circuit breaker: open after 5 consecutive failures, auto-reset after 60s
_embed_breaker = pybreaker.CircuitBreaker(
    fail_max=5,
    reset_timeout=60,
    name="embeddings",
)

if TYPE_CHECKING:
    from app.services.redis_cache import RedisCache

logger = logging.getLogger(__name__)


class _EmbedCache:
    """Simple TTL + LRU cache for single-text embeddings (query side)."""

    def __init__(self, ttl: float = 300.0, max_size: int = 256) -> None:
        self._ttl = ttl
        self._max_size = max_size
        self._store: dict[str, tuple[float, float, list[float]]] = {}  # key -> (created_at, last_access, vec)

    def get(self, key: str) -> list[float] | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        ts, _last, vec = entry
        if time.monotonic() - ts > self._ttl:
            del self._store[key]
            return None
        # Update last access time for LRU
        self._store[key] = (ts, time.monotonic(), vec)
        return vec

    def put(self, key: str, vec: list[float]) -> None:
        if len(self._store) >= self._max_size:
            # Evict least recently used entry
            lru_key = min(self._store, key=lambda k: self._store[k][1])
            del self._store[lru_key]
        now = time.monotonic()
        self._store[key] = (now, now, vec)


class EmbeddingService:
    """Generate text embeddings via Ollama's /api/embed endpoint."""

    def __init__(self, settings: Settings, redis_cache: "RedisCache | None" = None) -> None:
        self._url = f"{settings.ollama_base_url.rstrip('/')}/api/embed"
        self._model = settings.ollama_embed_model
        self._timeout = httpx.Timeout(
            connect=settings.ollama_connect_timeout,
            read=settings.ollama_read_timeout,
            write=10,
            pool=10,
        )
        self._vector_size = settings.qdrant_vector_size
        self._cache = _EmbedCache()
        self._redis = redis_cache
        # Persistent HTTP client — reused across requests
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self._timeout)
        return self._client

    async def close(self) -> None:
        """Close the persistent HTTP client. Called during app shutdown."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def embed(self, text: str) -> list[float]:
        """Return the embedding vector for a single query text (cached)."""
        prefixed = f"search_query: {text}"

        # L1: in-memory cache
        cached = self._cache.get(prefixed)
        if cached is not None:
            return cached

        # L2: Redis cache
        if self._redis and self._redis.available:
            redis_cached = await self._redis.get_embedding(prefixed)
            if redis_cached is not None:
                self._cache.put(prefixed, redis_cached)
                return redis_cached

        vectors = await self._embed_batch_raw([prefixed])
        self._cache.put(prefixed, vectors[0])

        # Write-through to Redis
        if self._redis and self._redis.available:
            await self._redis.set_embedding(prefixed, vectors[0], ttl=300)

        return vectors[0]

    async def embed_batch(
        self, texts: list[str], batch_size: int = 32
    ) -> list[list[float]]:
        """
        Embed a list of document texts in batches.
        Returns one vector per input text.
        Uses 'search_document:' prefix for nomic-embed-text.
        Checks in-memory and Redis cache before embedding.
        Failed batches are retried individually per-text before giving up.
        """
        import hashlib

        prefixed = [f"search_document: {t}" for t in texts]
        results: list[list[float] | None] = [None] * len(prefixed)
        to_embed: list[tuple[int, str]] = []  # (original_index, prefixed_text)

        # Check caches first — avoid re-embedding already-known texts
        for i, text in enumerate(prefixed):
            # L1: in-memory cache
            cached = self._cache.get(text)
            if cached is not None:
                results[i] = cached
                continue
            # L2: Redis cache
            if self._redis and self._redis.available:
                redis_cached = await self._redis.get_embedding(text)
                if redis_cached is not None:
                    self._cache.put(text, redis_cached)
                    results[i] = redis_cached
                    continue
            to_embed.append((i, text))

        if to_embed:
            # Embed only cache misses
            miss_texts = [t for _, t in to_embed]
            embedded: list[list[float]] = []
            for j in range(0, len(miss_texts), batch_size):
                batch = miss_texts[j : j + batch_size]
                try:
                    batch_vectors = await self._embed_batch_raw(batch)
                    embedded.extend(batch_vectors)
                except Exception as batch_exc:
                    logger.warning("Batch embed failed (%d texts), retrying individually: %s", len(batch), batch_exc)
                    for text in batch:
                        try:
                            single = await self._embed_batch_raw([text])
                            embedded.extend(single)
                        except Exception:
                            logger.error("Single embed failed, using zero vector for: %s", text[:60])
                            embedded.append([0.0] * self._vector_size)

            # Place results back and populate caches
            for k, (orig_idx, text) in enumerate(to_embed):
                vec = embedded[k]
                results[orig_idx] = vec
                self._cache.put(text, vec)
                if self._redis and self._redis.available:
                    await self._redis.set_embedding(text, vec, ttl=300)

        return results  # type: ignore[return-value]

    async def _embed_batch_raw(self, texts: list[str]) -> list[list[float]]:
        if _embed_breaker.current_state == "open":
            raise pybreaker.CircuitBreakerError("Embedding circuit breaker is open — service unavailable")

        @retry(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=1, max=10),
            retry=retry_if_exception_type((httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout)),
            reraise=True,
        )
        async def _call() -> list[list[float]]:
            client = await self._get_client()
            payload: dict[str, Any] = {"model": self._model, "input": texts}
            resp = await client.post(self._url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            # Ollama /api/embed returns {"embeddings": [[...], ...]}
            embeddings = data.get("embeddings", [])
            if len(embeddings) != len(texts):
                raise ValueError(
                    f"Expected {len(texts)} embeddings, got {len(embeddings)}"
                )
            return embeddings

        try:
            result = await _call()
            _embed_breaker.state.on_success()
            return result
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout) as exc:
            _embed_breaker.state.on_failure(exc)
            raise

    @property
    def vector_size(self) -> int:
        return self._vector_size
