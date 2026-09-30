"""
Redis shared cache layer.

Provides a unified async Redis client for caching embeddings and
semantic Q&A pairs across backend replicas. Falls back gracefully
when Redis is unavailable — the app works without it.
"""
from __future__ import annotations

import json
import logging
from typing import Any

import redis.asyncio as aioredis

from app.config import Settings

logger = logging.getLogger(__name__)


class RedisCache:
    """Async Redis cache wrapper with namespace-prefixed keys."""

    def __init__(self, settings: Settings) -> None:
        self._enabled = settings.redis_enabled
        self._ttl = settings.redis_ttl
        self._client: aioredis.Redis | None = None
        self._url = settings.redis_url

    async def connect(self) -> None:
        """Establish the Redis connection pool."""
        if not self._enabled:
            return
        try:
            self._client = aioredis.from_url(
                self._url,
                decode_responses=False,  # we store binary JSON
                socket_connect_timeout=3,
                socket_timeout=2,
            )
            await self._client.ping()
            logger.info("Redis connected: %s", self._url)
        except Exception as exc:
            logger.warning("Redis connection failed — falling back to in-memory cache: %s", exc)
            self._client = None

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()

    @property
    def available(self) -> bool:
        return self._enabled and self._client is not None

    # ── Embedding cache ───────────────────────────────────────────────────

    async def get_embedding(self, text: str) -> list[float] | None:
        """Retrieve a cached embedding vector."""
        if not self.available:
            return None
        try:
            raw = await self._client.get(f"emb:{text}")  # type: ignore[union-attr]
            if raw is None:
                return None
            return json.loads(raw)
        except Exception as exc:
            logger.debug("Redis get_embedding error: %s", exc)
            return None

    async def set_embedding(self, text: str, vector: list[float], ttl: int | None = None) -> None:
        """Cache an embedding vector with TTL."""
        if not self.available:
            return
        try:
            await self._client.setex(  # type: ignore[union-attr]
                f"emb:{text}",
                ttl or self._ttl,
                json.dumps(vector),
            )
        except Exception as exc:
            logger.debug("Redis set_embedding error: %s", exc)

    # ── Semantic Q&A cache ────────────────────────────────────────────────

    async def get_qa(self, question_hash: str) -> dict[str, Any] | None:
        """Retrieve a cached Q&A pair by question hash."""
        if not self.available:
            return None
        try:
            raw = await self._client.get(f"qa:{question_hash}")  # type: ignore[union-attr]
            if raw is None:
                return None
            return json.loads(raw)
        except Exception as exc:
            logger.debug("Redis get_qa error: %s", exc)
            return None

    async def set_qa(
        self, question_hash: str, data: dict[str, Any], ttl: int | None = None
    ) -> None:
        """Cache a Q&A pair."""
        if not self.available:
            return
        try:
            await self._client.setex(  # type: ignore[union-attr]
                f"qa:{question_hash}",
                ttl or self._ttl,
                json.dumps(data),
            )
        except Exception as exc:
            logger.debug("Redis set_qa error: %s", exc)

    async def invalidate_qa(self) -> None:
        """Clear all cached Q&A entries (pattern delete)."""
        if not self.available:
            return
        try:
            cursor = 0
            while True:
                cursor, keys = await self._client.scan(  # type: ignore[union-attr]
                    cursor=cursor, match="qa:*", count=500
                )
                if keys:
                    await self._client.delete(*keys)  # type: ignore[union-attr]
                if cursor == 0:
                    break
            logger.info("Redis: invalidated all Q&A cache entries")
        except Exception as exc:
            logger.warning("Redis invalidate_qa error: %s", exc)

    # ── Generic key-value ─────────────────────────────────────────────────

    async def get(self, key: str) -> bytes | None:
        if not self.available:
            return None
        try:
            return await self._client.get(key)  # type: ignore[union-attr]
        except Exception:
            return None

    async def set(self, key: str, value: bytes | str, ttl: int | None = None) -> None:
        if not self.available:
            return
        try:
            await self._client.setex(key, ttl or self._ttl, value)  # type: ignore[union-attr]
        except Exception:
            pass

    async def health(self) -> bool:
        if not self.available:
            return False
        try:
            return await self._client.ping()  # type: ignore[union-attr]
        except Exception:
            return False
