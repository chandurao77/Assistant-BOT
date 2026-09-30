"""
BM25 (Okapi BM25) scoring for hybrid search.

Builds an in-memory inverted index from Qdrant document payloads and scores
query terms using proper TF-IDF with document length normalization.  This
replaces the binary keyword match with frequency-weighted relevance scoring.

The index is built lazily on the first query and cached.  Call ``invalidate()``
after ingestion to force a rebuild on the next search.
"""
from __future__ import annotations

import logging
import math
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from app.models.schemas import SourceDocument

logger = logging.getLogger(__name__)

# ── BM25 hyperparameters ──────────────────────────────────────────────────
_K1 = 1.5    # Term frequency saturation — higher = more weight to repeated terms
_B = 0.75    # Document length normalization — 0 = no normalization, 1 = full

_STOP_WORDS = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "can", "shall", "how", "what", "where",
    "when", "who", "which", "why", "that", "this", "with", "from", "for",
    "and", "but", "not", "you", "your", "our", "its", "get", "set",
    "about", "into", "over", "also", "than",
})

_TOKEN_RE = re.compile(r"[a-zA-Z0-9_]+")
_CAMEL_SPLIT_RE = re.compile(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
# Normalize version/decimal numbers (e.g. "8.0" → "8_0") BEFORE tokenizing
# so they survive as a single discriminating token instead of being split into
# single-character fragments that are dropped by the len >= 2 filter.
_VERSION_RE = re.compile(r"\b(\d+)\.(\d+)\b")


def _split_camel(word: str) -> list[str]:
    """Split camelCase/PascalCase into sub-words.

    'accountTransfer' → ['account', 'transfer']
    'OrderAccountTransfer' → ['order', 'account', 'transfer']
    'API' → ['api']  (all-caps stays as one token)
    """
    parts = _CAMEL_SPLIT_RE.split(word)
    return [p.lower() for p in parts if len(p) >= 2]


def tokenize(text: str) -> list[str]:
    """Lowercase word tokenization with stop-word removal and camelCase splitting."""
    # Join version-like decimals before splitting so "8.0" → token "8_0"
    text = _VERSION_RE.sub(lambda m: f"{m.group(1)}_{m.group(2)}", text)
    tokens: list[str] = []
    for raw in _TOKEN_RE.findall(text):
        low = raw.lower()
        # Always include the full token (if valid)
        if len(low) >= 2 and low not in _STOP_WORDS:
            tokens.append(low)
        # Additionally split camelCase compounds into sub-words
        if raw != raw.lower() and raw != raw.upper():
            for part in _split_camel(raw):
                if part != low and part not in _STOP_WORDS:
                    tokens.append(part)
    return tokens


@dataclass
class _DocEntry:
    """Metadata for one indexed document (chunk)."""
    page_id: str
    title: str
    url: str
    space_key: str
    space_name: str
    text: str
    raw_text: str
    last_modified: str | None
    token_count: int  # total tokens in this doc (for length normalization)


@dataclass
class BM25Index:
    """In-memory BM25 inverted index over Qdrant document payloads."""

    # term → set of doc indices that contain the term
    inverted: dict[str, set[int]] = field(default_factory=dict)
    # term → doc_idx → term frequency count
    term_freqs: dict[str, dict[int, int]] = field(default_factory=dict)
    # all indexed documents
    docs: list[_DocEntry] = field(default_factory=list)
    # corpus statistics
    avg_doc_len: float = 0.0
    total_docs: int = 0
    built_at: float = 0.0

    def idf(self, term: str) -> float:
        """Inverse document frequency for a term."""
        if self.total_docs == 0:
            return 0.0
        df = len(self.inverted.get(term, set()))
        if df == 0:
            return 0.0
        # Standard BM25 IDF: log((N - df + 0.5) / (df + 0.5) + 1)
        return math.log((self.total_docs - df + 0.5) / (df + 0.5) + 1.0)

    def score(self, query_tokens: list[str], doc_idx: int) -> float:
        """BM25 score for a single document against tokenized query."""
        doc = self.docs[doc_idx]
        dl = doc.token_count
        score = 0.0
        for term in query_tokens:
            tf = self.term_freqs.get(term, {}).get(doc_idx, 0)
            if tf == 0:
                continue
            idf = self.idf(term)
            # BM25 TF component with length normalization
            numerator = tf * (_K1 + 1.0)
            denominator = tf + _K1 * (1.0 - _B + _B * dl / self.avg_doc_len)
            score += idf * numerator / denominator
        return score


class BM25Scorer:
    """Async BM25 scorer that builds its index from Qdrant."""

    def __init__(self) -> None:
        self._index: BM25Index | None = None

    @property
    def is_built(self) -> bool:
        return self._index is not None

    def invalidate(self) -> None:
        """Clear cached index so it rebuilds on next search."""
        self._index = None
        logger.info("BM25 index invalidated")

    def build_from_payloads(self, payloads: list[dict[str, Any]]) -> None:
        """Build the BM25 inverted index from Qdrant payload dicts.

        Each payload must have: page_id, title, text, url, space_key, space_name.
        """
        start = time.monotonic()
        index = BM25Index()
        total_tokens = 0

        for i, payload in enumerate(payloads):
            text = payload.get("text", "")
            title = payload.get("title", "")
            combined = f"{title} {text}"
            tokens = tokenize(combined)

            entry = _DocEntry(
                page_id=payload.get("page_id", ""),
                title=title,
                url=payload.get("url", ""),
                space_key=payload.get("space_key", ""),
                space_name=payload.get("space_name", ""),
                text=text,
                raw_text=payload.get("raw_text", "") or text,
                last_modified=payload.get("last_modified"),
                token_count=len(tokens),
            )
            index.docs.append(entry)
            total_tokens += len(tokens)

            # Build inverted index and term frequencies
            counts = Counter(tokens)
            for term, freq in counts.items():
                if term not in index.inverted:
                    index.inverted[term] = set()
                    index.term_freqs[term] = {}
                index.inverted[term].add(i)
                index.term_freqs[term][i] = freq

        index.total_docs = len(index.docs)
        index.avg_doc_len = total_tokens / max(index.total_docs, 1)
        index.built_at = time.monotonic()

        elapsed = time.monotonic() - start
        logger.info(
            "BM25 index built: %d docs, %d unique terms, avg_doc_len=%.1f (%.2fs)",
            index.total_docs, len(index.inverted), index.avg_doc_len, elapsed,
        )
        self._index = index

    def search(
        self,
        query_text: str,
        top_k: int = 10,
        space_keys: list[str] | None = None,
    ) -> list[SourceDocument]:
        """Score all indexed documents against the query and return top-K.

        Returns SourceDocument list sorted by BM25 score descending.
        """
        if not self._index or not self._index.docs:
            return []

        query_tokens = tokenize(query_text)
        if not query_tokens:
            return []

        space_set = set(space_keys) if space_keys else None

        # Score all candidate docs (only those containing at least one query term)
        candidate_indices: set[int] = set()
        for token in query_tokens:
            candidate_indices |= self._index.inverted.get(token, set())

        scored: list[tuple[float, int]] = []
        for doc_idx in candidate_indices:
            doc = self._index.docs[doc_idx]
            # Space filter
            if space_set and doc.space_key not in space_set:
                continue
            s = self._index.score(query_tokens, doc_idx)
            if s > 0:
                scored.append((s, doc_idx))

        # Sort by score descending, take top_k
        scored.sort(key=lambda x: -x[0])
        scored = scored[:top_k]

        # Normalize scores to 0–1 range (max-normalize)
        max_score = scored[0][0] if scored else 1.0

        # Deduplicate by page_id (keep highest-scoring chunk per page)
        seen_pages: set[str] = set()
        results: list[SourceDocument] = []
        for bm25_score, doc_idx in scored:
            doc = self._index.docs[doc_idx]
            if doc.page_id in seen_pages:
                continue
            seen_pages.add(doc.page_id)
            display_text = doc.raw_text or doc.text
            results.append(SourceDocument(
                page_id=doc.page_id,
                title=doc.title,
                url=doc.url,
                space_key=doc.space_key,
                space_name=doc.space_name,
                excerpt=display_text[:500],
                content=display_text,
                score=round(bm25_score / max_score, 4),
                last_modified=doc.last_modified,
            ))

        return results
