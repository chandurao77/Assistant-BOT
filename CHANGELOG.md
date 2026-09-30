# Changelog

All notable changes to Assistant Bot are documented in this file.

## [Unreleased]

### Fixed
- **full_refresh data loss** — `full_refresh: true` with specific `space_keys` no longer drops the entire Qdrant collection. Added `VectorStore.delete_spaces()` to delete only the targeted spaces' vectors, leaving all other spaces intact. A full wipe (no `space_keys`) still drops and recreates the collection.

### Changed
- **Backend host port changed from 8000 to 8005** — Host-side port mapping updated to `8005:8000` in `docker-compose.yml` to avoid conflicts. Internal container-to-container communication still uses port `8000`. Frontend nginx proxy and all documentation updated accordingly.
- **Frontend nginx resolver** — Replaced hardcoded `10.89.0.1` DNS resolver with a dynamic resolver injected at container startup from `/etc/resolv.conf` via `docker-entrypoint.sh`. Fixes login failures after Podman network recreation.

### Added
- **BM25 Hybrid Search** — Replaced binary keyword matching with Okapi BM25 term-frequency scoring (k1=1.5, b=0.75) for the keyword leg of hybrid search. In-memory inverted index built lazily from Qdrant on first query, invalidated after each ingestion. Toggle with `BM25_ENABLED=true` (default). Falls back to Qdrant `MatchText` when disabled.
- **Contextual Chunking** — Each chunk now stores an enriched `text` field with metadata prefix (`Source: {title} | Space: {space} | Section: {heading} | {content}`) for better embedding and keyword retrieval. Original raw text preserved in `raw_text` payload field for clean citation display. Toggle with `CONTEXTUAL_CHUNKING_ENABLED=true` (default). Requires re-ingestion to take effect.
- `backend/app/services/bm25.py` — BM25 scoring engine with `BM25Scorer`, `BM25Index`, `tokenize()`.
- `backend/tests/test_bm25.py` — 24 unit tests for BM25 module.
- `backend/tests/test_contextual_chunking.py` — 16 unit tests for contextual chunking.
- Section heading tracking in `text_splitter.py` — `Chunk` dataclass now carries `section_heading` extracted from markdown-style headings.
- `DocumentChunk.enrich_text()` method and `raw_text` payload field in `document.py`.
- BM25 index invalidation in all 6 ingestion paths (local, Confluence, Jira, GitHub, MCP, wiki-kb).

### Changed
- `vector_store.py` — Search results now use `raw_text` for citation display (`excerpt`/`content`), falling back to `text` for backward compatibility with pre-enrichment data.
- `vector_store.py` — Keyword search leg conditionally uses BM25 scorer or legacy `_keyword_search` based on `BM25_ENABLED` flag.
- `bm25.py` — `_DocEntry` and search results use `raw_text` for clean citation output.
- All ingestion paths in `ingest.py` and `upload.py` call `enrich_text()` when contextual chunking is enabled.
