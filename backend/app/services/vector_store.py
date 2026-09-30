"""Qdrant vector store wrapper for Confluence document chunks."""
from __future__ import annotations
import hashlib
import logging
import uuid
from typing import Any

import httpx
import pybreaker
from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models as qmodels

from app.config import Settings
from app.models.document import DocumentChunk
from app.models.schemas import SourceDocument
from app.services.bm25 import BM25Scorer

logger = logging.getLogger(__name__)

# ── Reciprocal Rank Fusion ────────────────────────────────────────────────
_RRF_K = 60  # Standard RRF constant — prevents top-ranked items from dominating


def reciprocal_rank_fusion(
    vector_docs: list[SourceDocument],
    keyword_docs: list[SourceDocument],
) -> list[SourceDocument]:
    """Merge vector and keyword results using Reciprocal Rank Fusion (RRF).

    Documents appearing in BOTH result sets rank higher than those in only one.
    This is mathematically superior to simple interleaving.
    """
    scores: dict[str, float] = {}
    docs: dict[str, SourceDocument] = {}

    for rank, doc in enumerate(vector_docs, start=1):
        scores[doc.page_id] = scores.get(doc.page_id, 0.0) + 1.0 / (_RRF_K + rank)
        docs[doc.page_id] = doc  # vector version has real cosine score

    for rank, doc in enumerate(keyword_docs, start=1):
        scores[doc.page_id] = scores.get(doc.page_id, 0.0) + 1.0 / (_RRF_K + rank)
        if doc.page_id not in docs:
            docs[doc.page_id] = doc

    # Sort by RRF score descending; update the doc's display score
    ranked = sorted(scores.items(), key=lambda x: -x[1])
    result: list[SourceDocument] = []
    for page_id, rrf_score in ranked:
        doc = docs[page_id]
        # Preserve original vector score if available, else use keyword score
        result.append(doc)
    return result


# ── Per-source-type limits ────────────────────────────────────────────────
# Prevents one source type from dominating the result set
_MAX_PER_SOURCE_TYPE = {
    "__GITHUB__": 4,     # Code files — cap to prevent drowning docs
    "__JIRA__": 4,       # Jira issues
    "__UPLOAD__": 3,     # Uploaded files
    "__LEARNED__": 2,    # Verified Q&A pairs
    # Confluence (all other space_keys) — no limit
}
_DEFAULT_SOURCE_LIMIT = 10  # Confluence and unknown sources


def apply_source_type_limits(docs: list[SourceDocument]) -> list[SourceDocument]:
    """Cap the number of results per source type to ensure diversity."""
    counts: dict[str, int] = {}
    result: list[SourceDocument] = []
    for doc in docs:
        # Determine source type: special prefixed keys or "confluence"
        source_type = doc.space_key if doc.space_key.startswith("__") else "_confluence_"
        limit = _MAX_PER_SOURCE_TYPE.get(source_type, _DEFAULT_SOURCE_LIMIT)
        counts[source_type] = counts.get(source_type, 0) + 1
        if counts[source_type] <= limit:
            result.append(doc)
    return result


# Circuit breaker: open after 5 consecutive failures, auto-reset after 60s
_qdrant_breaker = pybreaker.CircuitBreaker(
    fail_max=5,
    reset_timeout=60,
    name="qdrant",
)


class VectorStore:
    """Async Qdrant client wrapper: index and search DocumentChunks."""

    def __init__(self, settings: Settings) -> None:
        self._client = AsyncQdrantClient(
            host=settings.qdrant_host,
            port=settings.qdrant_port,
            prefer_grpc=False,
            timeout=30,
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )
        self._collection = settings.qdrant_collection
        self._vector_size = settings.qdrant_vector_size
        self._bm25_enabled = settings.bm25_enabled
        self._bm25 = BM25Scorer()

    async def ensure_collection(self, drop_existing: bool = False) -> None:
        """Create the collection if it doesn't exist (or recreate if requested)."""
        exists = await self._collection_exists()
        if drop_existing and exists:
            await self._client.delete_collection(self._collection)
            exists = False

        if not exists:
            await self._client.create_collection(
                collection_name=self._collection,
                vectors_config=qmodels.VectorParams(
                    size=self._vector_size,
                    distance=qmodels.Distance.COSINE,
                ),
                optimizers_config=qmodels.OptimizersConfigDiff(
                    indexing_threshold=20_000,
                ),
                hnsw_config=qmodels.HnswConfigDiff(
                    m=16,
                    ef_construct=100,
                ),
            )
            logger.info("Created Qdrant collection '%s'", self._collection)
        else:
            logger.info("Using existing Qdrant collection '%s'", self._collection)

        # Ensure full-text indexes exist for hybrid search
        await self._ensure_text_indexes()

    async def upsert_chunks(
        self, chunks: list[DocumentChunk], vectors: list[list[float]]
    ) -> None:
        """Upsert document chunks with their embedding vectors."""
        if not chunks:
            return

        points = [
            qmodels.PointStruct(
                id=str(uuid.uuid5(uuid.NAMESPACE_DNS, chunk.chunk_id)),
                vector=vector,
                payload=chunk.to_qdrant_payload(),
            )
            for chunk, vector in zip(chunks, vectors)
        ]

        # Upsert in batches of 100
        batch_size = 100
        for i in range(0, len(points), batch_size):
            await self._client.upsert(
                collection_name=self._collection,
                points=points[i : i + batch_size],
                wait=True,
            )

    async def delete_page(self, page_id: str) -> None:
        """Remove all chunks belonging to a specific page."""
        await self._client.delete(
            collection_name=self._collection,
            points_selector=qmodels.FilterSelector(
                filter=qmodels.Filter(
                    must=[
                        qmodels.FieldCondition(
                            key="page_id",
                            match=qmodels.MatchValue(value=page_id),
                        )
                    ]
                )
            ),
        )

    async def delete_spaces(self, space_keys: list[str]) -> None:
        """Remove all chunks belonging to specific Confluence spaces."""
        await self._client.delete(
            collection_name=self._collection,
            points_selector=qmodels.FilterSelector(
                filter=qmodels.Filter(
                    must=[
                        qmodels.FieldCondition(
                            key="space_key",
                            match=qmodels.MatchAny(any=space_keys),
                        )
                    ]
                )
            ),
        )
        logger.info("Deleted all chunks for spaces: %s", space_keys)

    async def search(
        self,
        query_vector: list[float],
        top_k: int = 5,
        score_threshold: float = 0.35,
        space_keys: list[str] | None = None,
        query_text: str = "",
    ) -> list[SourceDocument]:
        if _qdrant_breaker.current_state == "open":
            logger.warning("Qdrant circuit breaker OPEN — skipping search")
            return []

        query_filter: qmodels.Filter | None = None
        if space_keys:
            query_filter = qmodels.Filter(
                must=[
                    qmodels.FieldCondition(
                        key="space_key",
                        match=qmodels.MatchAny(any=space_keys),
                    )
                ]
            )

        # 1. Primary vector search (skip if no vector provided — BM25-only mode)
        vector_docs: list[SourceDocument] = []
        if query_vector:
            try:
                results = await self._client.search(
                    collection_name=self._collection,
                    query_vector=query_vector,
                    limit=top_k,
                    score_threshold=score_threshold,
                    query_filter=query_filter,
                    with_payload=True,
                )
            except (httpx.HTTPError, OSError) as exc:
                _qdrant_breaker.state.on_failure(exc)
                logger.error("Qdrant search failed (state=%s): %s", _qdrant_breaker.current_state, exc)
                return []
            else:
                _qdrant_breaker.state.on_success()

            # Build doc list from vector results
            seen: set[str] = set()
            for hit in results:
                payload: dict[str, Any] = hit.payload or {}
                page_id = payload.get("page_id", "")
                if page_id in seen:
                    continue
                seen.add(page_id)
                full_text = payload.get("text", "")
                display_text = payload.get("raw_text", "") or full_text
                vector_docs.append(SourceDocument(
                    page_id=page_id,
                    title=payload.get("title", ""),
                    url=payload.get("url", ""),
                    space_key=payload.get("space_key", ""),
                    space_name=payload.get("space_name", ""),
                    excerpt=display_text[:500],
                    content=display_text,
                    score=round(hit.score, 4),
                    last_modified=payload.get("last_modified"),
                    page_type=payload.get("page_type", ""),
                    labels=payload.get("labels", []),
                    ancestor_titles=payload.get("ancestor_titles", []),
                    related_concepts=payload.get("related_concepts", []),
                ))

        # 2. Secondary keyword/BM25 search
        keyword_docs: list[SourceDocument] = []
        if query_text:
            if self._bm25_enabled:
                await self._ensure_bm25_index()
                keyword_docs = self._bm25.search(query_text, top_k=top_k, space_keys=space_keys)
            else:
                keyword_docs = await self._keyword_search(query_text, space_keys, limit=top_k)

        # 3. Merge using Reciprocal Rank Fusion (documents in BOTH rank higher)
        if keyword_docs:
            merged = reciprocal_rank_fusion(vector_docs, keyword_docs)
        else:
            merged = vector_docs

        # 4. Apply per-source-type limits (prevent code from drowning docs)
        return apply_source_type_limits(merged)

    async def fetch_by_page_ids(self, page_ids: list[str]) -> list[SourceDocument]:
        """
        Fetch one representative chunk per page using a payload filter (scroll).
        Used for graph-RAG link expansion — no query vector required.
        """
        if not page_ids:
            return []
        results, _offset = await self._client.scroll(
            collection_name=self._collection,
            scroll_filter=qmodels.Filter(
                must=[
                    qmodels.FieldCondition(
                        key="page_id",
                        match=qmodels.MatchAny(any=page_ids),
                    )
                ]
            ),
            limit=len(page_ids) * 3,
            with_payload=True,
            with_vectors=False,
        )
        seen: dict[str, SourceDocument] = {}
        for record in results:
            payload: dict[str, Any] = record.payload or {}
            pid = payload.get("page_id", "")
            if pid and pid not in seen:
                full_text = payload.get("text", "")
                display_text = payload.get("raw_text", "") or full_text
                seen[pid] = SourceDocument(
                    page_id=pid,
                    title=payload.get("title", ""),
                    url=payload.get("url", ""),
                    space_key=payload.get("space_key", ""),
                    space_name=payload.get("space_name", ""),
                    excerpt=display_text[:500],
                    content=display_text,
                    score=0.0,
                    last_modified=payload.get("last_modified"),
                    page_type=payload.get("page_type", ""),
                    labels=payload.get("labels", []),
                    ancestor_titles=payload.get("ancestor_titles", []),
                )
        return list(seen.values())

    async def index_qa_pair(
        self,
        message_id: str,
        question: str,
        answer: str,
        question_vector: list[float],
    ) -> None:
        """
        Index a verified Q&A pair into Qdrant (triggered by positive feedback).
        Uses a content-hash as the deterministic point ID so identical Q&A content
        always maps to the same Qdrant point — prevents duplicate entries when the
        same question receives multiple positive votes.
        """
        content_hash = hashlib.sha256(
            f"{question.strip()}\n{answer.strip()}".encode()
        ).hexdigest()
        point = qmodels.PointStruct(
            id=str(uuid.uuid5(uuid.NAMESPACE_DNS, f"qa_content_{content_hash}")),
            vector=question_vector,
            payload={
                "page_id": f"qa_{message_id}",
                "title": f"Q: {question[:80]}",
                "url": "",
                "space_key": "__LEARNED__",
                "space_name": "Verified Answers",
                "text": f"Question: {question}\n\nAnswer: {answer}",
                "chunk_index": 0,
            },
        )
        await self._client.upsert(
            collection_name=self._collection,
            points=[point],
            wait=True,
        )
        logger.info("Self-learn: indexed verified Q&A (hash=%s)", content_hash[:8])

    async def remove_learned_qa(self, message_id: str) -> None:
        """Remove a previously-learned Q&A pair from Qdrant (triggered by negative feedback)."""
        await self._client.delete(
            collection_name=self._collection,
            points_selector=qmodels.FilterSelector(
                filter=qmodels.Filter(
                    must=[
                        qmodels.FieldCondition(
                            key="page_id",
                            match=qmodels.MatchValue(value=f"qa_{message_id}"),
                        )
                    ]
                )
            ),
        )
        logger.info("Self-learn: removed Q&A for message %s", message_id)

    async def count(self) -> int:
        info = await self._client.get_collection(self._collection)
        return info.points_count or 0

    async def list_titles(self) -> list[str]:
        """Return all unique document titles from Qdrant (for spell dictionary)."""
        try:
            titles: set[str] = set()
            offset = None
            while True:
                result, next_offset = await self._client.scroll(
                    collection_name=self._collection,
                    limit=1000,
                    offset=offset,
                    with_payload=["title"],
                    with_vectors=False,
                )
                for point in result:
                    title = (point.payload or {}).get("title", "")
                    if title:
                        titles.add(title)
                if next_offset is None:
                    break
                offset = next_offset
            return list(titles)
        except (httpx.HTTPError, OSError):
            return []

    async def list_page_id_title_pairs(self) -> list[tuple[str, str]]:
        """Return all unique (page_id, title) pairs from Qdrant.

        Used by the OKF graph enricher to resolve [[ConceptName]] links to page IDs.
        One representative point per page_id is collected via payload scroll.
        """
        try:
            seen: dict[str, str] = {}   # page_id → title
            offset = None
            while True:
                result, next_offset = await self._client.scroll(
                    collection_name=self._collection,
                    limit=1000,
                    offset=offset,
                    with_payload=["page_id", "title"],
                    with_vectors=False,
                )
                for point in result:
                    payload = point.payload or {}
                    pid = payload.get("page_id", "")
                    title = payload.get("title", "")
                    if pid and pid not in seen:
                        seen[pid] = title
                if next_offset is None:
                    break
                offset = next_offset
            return list(seen.items())
        except (httpx.HTTPError, OSError):
            return []

    async def list_spaces(self) -> list[dict]:
        """Return distinct space_key + space_name pairs indexed in Qdrant."""
        try:
            # Scroll through all payloads and collect unique spaces
            seen: dict[str, str] = {}
            offset = None
            while True:
                result, next_offset = await self._client.scroll(
                    collection_name=self._collection,
                    scroll_filter=qmodels.Filter(
                        must_not=[
                            qmodels.FieldCondition(
                                key="space_key",
                                match=qmodels.MatchValue(value="__LEARNED__"),
                            )
                        ]
                    ),
                    limit=1000,
                    offset=offset,
                    with_payload=["space_key", "space_name"],
                    with_vectors=False,
                )
                for point in result:
                    sk = (point.payload or {}).get("space_key", "")
                    sn = (point.payload or {}).get("space_name", sk)
                    if sk and sk not in seen:
                        seen[sk] = sn
                if next_offset is None:
                    break
                offset = next_offset
            return [{"space_key": k, "space_name": v} for k, v in sorted(seen.items())]
        except (httpx.HTTPError, OSError):
            return []

    async def health(self) -> bool:
        try:
            await self._client.get_collections()
            return True
        except (httpx.HTTPError, OSError):
            return False

    # ── BM25 index management ─────────────────────────────────────────────

    def invalidate_bm25(self) -> None:
        """Clear BM25 index so it rebuilds on next search. Call after ingestion."""
        self._bm25.invalidate()

    async def _ensure_bm25_index(self) -> None:
        """Build the BM25 index from Qdrant if not already cached."""
        if self._bm25.is_built:
            return
        logger.info("Building BM25 index from Qdrant collection '%s'...", self._collection)
        payloads: list[dict[str, Any]] = []
        offset = None
        while True:
            results, next_offset = await self._client.scroll(
                collection_name=self._collection,
                limit=500,
                offset=offset,
                with_payload=["page_id", "title", "text", "url", "space_key", "space_name", "last_modified"],
                with_vectors=False,
            )
            for record in results:
                if record.payload:
                    payloads.append(record.payload)
            if next_offset is None:
                break
            offset = next_offset
        self._bm25.build_from_payloads(payloads)

    async def _ensure_text_indexes(self) -> None:
        """Create full-text payload indexes on title and text fields for keyword search."""
        for field in ("title", "text"):
            try:
                await self._client.create_payload_index(
                    collection_name=self._collection,
                    field_name=field,
                    field_schema=qmodels.TextIndexParams(
                        type="text",
                        tokenizer=qmodels.TokenizerType.WORD,
                        min_token_len=2,
                        max_token_len=30,
                        lowercase=True,
                    ),
                    wait=True,
                )
            except Exception:
                pass  # Index may already exist

    _STOP_WORDS = frozenset({
        "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
        "have", "has", "had", "do", "does", "did", "will", "would", "could",
        "should", "may", "might", "can", "shall", "how", "what", "where",
        "when", "who", "which", "why", "that", "this", "with", "from", "for",
        "and", "but", "not", "you", "your", "our", "its", "get", "set",
        "about", "into", "over", "also", "than",
    })

    async def _keyword_search(
        self,
        query_text: str,
        space_keys: list[str] | None = None,
        limit: int = 5,
    ) -> list[SourceDocument]:
        """Full-text keyword search on title and text payload fields.

        Uses OR logic — a document matches if ANY keyword appears in the
        searched field.  This catches sections whose titles contain the
        user's terms even when the embedding model ranks them low.
        """
        words = [
            w for raw in query_text.split()
            if len(w := raw.strip(",.?!:;\"'()")) >= 3
            and w.lower() not in self._STOP_WORDS
        ]
        if not words:
            return []

        docs: list[SourceDocument] = []
        seen_ids: set[str] = set()

        for field, kw_score in (("title", 0.65), ("text", 0.50)):
            # OR logic: match any keyword in the field
            should_conditions = [
                qmodels.FieldCondition(
                    key=field,
                    match=qmodels.MatchText(text=word),
                )
                for word in words
            ]
            must_conditions: list[qmodels.FieldCondition] = []
            if space_keys:
                must_conditions.append(
                    qmodels.FieldCondition(
                        key="space_key",
                        match=qmodels.MatchAny(any=space_keys),
                    )
                )

            try:
                results, _ = await self._client.scroll(
                    collection_name=self._collection,
                    scroll_filter=qmodels.Filter(
                        should=should_conditions,
                        must=must_conditions or None,
                    ),
                    limit=limit,
                    with_payload=True,
                    with_vectors=False,
                )
                for record in results:
                    payload = record.payload or {}
                    page_id = payload.get("page_id", "")
                    if page_id in seen_ids:
                        continue
                    seen_ids.add(page_id)
                    full_text = payload.get("text", "")
                    docs.append(SourceDocument(
                        page_id=page_id,
                        title=payload.get("title", ""),
                        url=payload.get("url", ""),
                        space_key=payload.get("space_key", ""),
                        space_name=payload.get("space_name", ""),
                        excerpt=full_text[:500],
                        content=full_text,
                        score=kw_score,  # title matches scored higher than text matches
                        last_modified=payload.get("last_modified"),
                    ))
            except Exception as exc:
                logger.debug("Keyword search on '%s' failed: %s", field, exc)

        return docs

    async def _collection_exists(self) -> bool:
        collections = await self._client.get_collections()
        return any(c.name == self._collection for c in collections.collections)
