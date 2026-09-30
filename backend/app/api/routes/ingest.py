"""Ingestion trigger endpoint — kicks off Confluence → Qdrant pipeline."""
from __future__ import annotations
import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status

from app.config import Settings, get_settings
from app.api.dependencies import verify_api_key
from app.models.schemas import IngestRequest, IngestResponse, JiraIngestRequest, GitHubIngestRequest, PushPagesRequest, PushPagePayload
from app.services.confluence import ConfluenceClient
from app.services.jira import JiraClient, issue_to_chunks
from app.services.github_client import GitHubClient, file_to_chunk, pr_to_chunk
from app.services.local_loader import load_local_docs
from app.services.embeddings import EmbeddingService
from app.services.vector_store import VectorStore
from app.services.semantic_cache import SemanticCache
from app.services.entity_store import EntityStore
from app.utils.html_parser import html_to_text, extract_confluence_links
from app.utils.text_splitter import split_text
from app.models.document import DocumentChunk
from app.services.rag import refresh_spell_dictionary

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/ingest", tags=["ingest"])

# Simple in-memory lock — prevents concurrent ingestion runs
_ingest_lock = asyncio.Lock()
_ingest_status: dict = {
    "running": False,
    "start_time": None,
    "end_time": None,
    "source": None,
    "current_page": 0,
    "total_pages": 0,
    "pages_skipped": 0,
    "percent": 0,
    "last_result": None,
}


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _update_progress(source: str, current: int, total: int, skipped: int = 0) -> None:
    """Update the in-memory ingestion progress (called per page)."""
    _ingest_status["source"] = source
    _ingest_status["current_page"] = current
    _ingest_status["total_pages"] = total
    _ingest_status["pages_skipped"] = skipped
    _ingest_status["percent"] = round((current / total) * 100) if total > 0 else 0


def _enrich_chunks(chunks: list[DocumentChunk], *, enabled: bool) -> None:
    """Apply contextual enrichment to chunks in-place when the feature is on."""
    if not enabled:
        return
    for chunk in chunks:
        chunk.enrich_text()


@router.post("", response_model=IngestResponse, status_code=status.HTTP_202_ACCEPTED)
async def trigger_ingest(
    request_body: IngestRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    settings: Settings = Depends(get_settings),
    _auth: None = Depends(verify_api_key),
):
    """
    Trigger asynchronous ingestion of Confluence content into Qdrant.
    Returns 202 immediately; progress can be checked via GET /ingest/status.
    """
    if _ingest_lock.locked():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ingestion is already running. Check /api/ingest/status.",
        )

    store = request.app.state.conversation_store
    semantic_cache = request.app.state.pipeline.semantic_cache
    entity_store = getattr(request.app.state, "entity_store", None)
    background_tasks.add_task(
        _run_ingestion,
        settings=settings,
        space_keys=request_body.space_keys,
        full_refresh=request_body.full_refresh,
        fill_gaps=request_body.fill_gaps,
        conversation_store=store,
        semantic_cache=semantic_cache,
        entity_store=entity_store,
    )
    return IngestResponse(
        status="accepted",
        pages_processed=0,
        chunks_indexed=0,
        errors=[],
    )


@router.get("/status")
async def ingest_status():
    """Return current ingestion status and last-run summary."""
    result = dict(_ingest_status)
    if result["running"]:
        result["status"] = "running"
    elif result["end_time"]:
        result["status"] = "completed"
    else:
        result["status"] = "idle"
    # Include pages_processed from last_result for backwards compatibility
    if result.get("last_result"):
        result["pages_processed"] = result["last_result"].get("pages_processed", 0)
    elif result["running"]:
        result["pages_processed"] = result["current_page"]
    return result


@router.get("/spaces/discover")
async def discover_spaces(
    settings: Settings = Depends(get_settings),
    _auth: None = Depends(verify_api_key),
):
    """Discover all Confluence spaces accessible with the configured API token.

    Returns a list of spaces with their key, name, and type so admins can
    select which spaces to ingest without manually editing .env.
    """
    if not settings.confluence_base_url or not settings.confluence_api_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Confluence credentials not configured. Set CONFLUENCE_BASE_URL, CONFLUENCE_EMAIL, and CONFLUENCE_API_TOKEN in .env.",
        )
    try:
        async with ConfluenceClient(settings) as confluence:
            raw_spaces = await confluence.get_spaces()
        return [
            {
                "key": s.get("key", ""),
                "name": s.get("name", ""),
                "type": s.get("type", "global"),
            }
            for s in raw_spaces
            if s.get("key")
        ]
    except Exception as exc:
        logger.error("Space discovery failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to connect to Confluence: {exc}",
        )


@router.post("/local", response_model=IngestResponse, status_code=status.HTTP_202_ACCEPTED)
async def trigger_local_ingest(
    background_tasks: BackgroundTasks,
    request: Request,
    full_refresh: bool = False,
    docs_dir: str = "/app/test_docs",
    settings: Settings = Depends(get_settings),
    _auth: None = Depends(verify_api_key),
):
    """
    Ingest local documents from the test_docs folder into Qdrant.
    No Confluence credentials required — for testing and development.

    - docs_dir: path inside the container (default: /app/test_docs)
    - full_refresh: drop and rebuild the entire index
    """
    if _ingest_lock.locked():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ingestion is already running. Check /api/ingest/status.",
        )

    # Path traversal protection — restrict to allowed base directory
    _ALLOWED_BASE = Path("/app/test_docs").resolve()
    docs_path = Path(docs_dir).resolve()
    if not str(docs_path).startswith(str(_ALLOWED_BASE)):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"docs_dir must be within /app/test_docs. Got: {docs_dir}",
        )
    if not docs_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"docs_dir not found: {docs_dir}. Make sure test_docs/ is mounted.",
        )

    store = request.app.state.conversation_store
    semantic_cache = request.app.state.pipeline.semantic_cache
    entity_store = getattr(request.app.state, "entity_store", None)
    background_tasks.add_task(
        _run_local_ingestion,
        settings=settings,
        docs_dir=docs_path,
        full_refresh=full_refresh,
        conversation_store=store,
        semantic_cache=semantic_cache,
        entity_store=entity_store,
    )
    return IngestResponse(status="accepted", pages_processed=0, chunks_indexed=0, errors=[])


async def _run_local_ingestion(
    settings: Settings,
    docs_dir: Path,
    full_refresh: bool,
    conversation_store=None,
    semantic_cache: SemanticCache | None = None,
    entity_store: EntityStore | None = None,
) -> None:
    async with _ingest_lock:
        _ingest_status["running"] = True
        _ingest_status["start_time"] = _utcnow()
        _ingest_status["end_time"] = None
        _update_progress("local", 0, 0)
        pages_processed = 0
        chunks_indexed = 0
        skipped = 0
        errors: list[str] = []

        embed_service = EmbeddingService(settings)
        vector_store = VectorStore(settings)

        try:
            if full_refresh and conversation_store:
                await conversation_store.clear_page_index()
            await vector_store.ensure_collection(drop_existing=full_refresh)
            pages = load_local_docs(docs_dir)
            total_pages = len(pages)
            _update_progress("local", 0, total_pages)

            # Get known page versions for incremental skip
            all_page_ids = [p.page_id for p in pages]
            existing_versions: dict[str, str] = {}
            if conversation_store and not full_refresh:
                existing_versions = await conversation_store.get_page_versions(all_page_ids)

            for idx, page in enumerate(pages, 1):
                _update_progress("local", idx, total_pages, skipped)
                try:
                    # Incremental skip: same last_modified means nothing changed
                    new_lm = page.last_modified.isoformat()
                    if not full_refresh and existing_versions.get(page.page_id) == new_lm:
                        skipped += 1
                        logger.debug("Skipping unchanged local doc '%s'", page.title)
                        continue

                    plain = html_to_text(page.body_html) if "<" in page.body_html else page.body_html
                    if not plain.strip():
                        continue

                    raw_chunks = split_text(plain, chunk_size=settings.chunk_size, chunk_overlap=settings.chunk_overlap)
                    doc_chunks = [
                        DocumentChunk(
                            chunk_id=f"{page.page_id}_{c.index}",
                            page_id=page.page_id,
                            title=page.title,
                            space_key=page.space_key,
                            space_name=page.space_name,
                            url=page.url,
                            text=c.text,
                            chunk_index=c.index,
                            total_chunks=len(raw_chunks),
                            last_modified=page.last_modified,
                            section_heading=c.section_heading,
                            labels=page.labels,
                            ancestor_titles=page.ancestor_titles,
                        )
                        for c in raw_chunks
                    ]
                    _enrich_chunks(doc_chunks, enabled=settings.contextual_chunking_enabled)

                    # Delete existing chunks before re-upserting (prevents duplicates)
                    await vector_store.delete_page(page.page_id)
                    vectors = await embed_service.embed_batch([c.text for c in doc_chunks])
                    await vector_store.upsert_chunks(doc_chunks, vectors)

                    # Entity extraction (Cognee-lite) — extract and store entities
                    if entity_store and settings.entity_extraction_enabled:
                        try:
                            await entity_store.extract_and_store(page.page_id, plain)
                        except Exception as exc:
                            logger.warning("Entity extraction failed for '%s': %s", page.title, exc)

                    # Update page index — rollback vectors on failure
                    if conversation_store:
                        try:
                            await conversation_store.upsert_page_index(
                                page.page_id, new_lm, len(doc_chunks)
                            )
                            linked_ids = extract_confluence_links(page.body_html)
                            if linked_ids:
                                await conversation_store.upsert_page_links(page.page_id, linked_ids)
                        except Exception as idx_exc:
                            logger.error("Page index update failed for '%s', rolling back vectors: %s", page.title, idx_exc)
                            await vector_store.delete_page(page.page_id)
                            raise

                    pages_processed += 1
                    chunks_indexed += len(doc_chunks)
                    logger.info("page_ingested", source="local", title=page.title, chunks=len(doc_chunks), page_id=page.page_id)

                except Exception as exc:
                    err = f"{page.title}: {exc}"
                    logger.warning("page_ingest_failed", source="local", title=page.title, error=str(exc))
                    errors.append(err)

        except Exception as exc:
            logger.exception("ingestion_fatal", source="local", error=str(exc))
            errors.append(f"Fatal: {exc}")
        finally:
            _ingest_status["running"] = False
            _ingest_status["end_time"] = _utcnow()
            _ingest_status["last_result"] = {
                "source": "local",
                "pages_processed": pages_processed,
                "pages_skipped": skipped,
                "chunks_indexed": chunks_indexed,
                "errors": errors,
            }
            logger.info("ingestion_complete", source="local", pages=pages_processed, skipped=skipped, chunks=chunks_indexed, errors=len(errors))

            # Invalidate semantic cache after ingestion so stale answers aren't served
            if semantic_cache and pages_processed > 0:
                try:
                    await semantic_cache.invalidate()
                    logger.info("Semantic cache invalidated after local ingestion")
                except Exception as exc:
                    logger.warning("Failed to invalidate semantic cache: %s", exc)

            # Refresh spell dictionary with words from ingested titles
            if chunks_indexed > 0:
                try:
                    titles = await vector_store.list_titles()
                    refresh_spell_dictionary(titles)
                except Exception as exc:
                    logger.warning("Failed to refresh spell dictionary: %s", exc)
                vector_store.invalidate_bm25()


async def _run_ingestion(
    settings: Settings,
    space_keys: list[str] | None,
    full_refresh: bool,
    fill_gaps: bool = False,
    conversation_store=None,
    semantic_cache: SemanticCache | None = None,
    entity_store: EntityStore | None = None,
) -> None:
    async with _ingest_lock:
        _ingest_status["running"] = True
        _ingest_status["start_time"] = _utcnow()
        _ingest_status["end_time"] = None
        _update_progress("confluence", 0, 0)
        pages_processed = 0
        chunks_indexed = 0
        skipped = 0
        errors: list[str] = []

        embed_service = EmbeddingService(settings)
        vector_store = VectorStore(settings)

        try:
            await vector_store.ensure_collection(drop_existing=False)
            # full_refresh: clear page_index for targeted spaces so incremental skip
            # is bypassed and every page gets re-processed. Existing Qdrant chunks are
            # replaced page-by-page below (delete_page + upsert), so there is no gap
            # window where a space has zero data.
            # full_refresh with no space filter: drop entire collection + full index wipe.
            if full_refresh:
                if space_keys:
                    if conversation_store:
                        await conversation_store.clear_page_index(space_keys=space_keys)
                else:
                    if conversation_store:
                        await conversation_store.clear_page_index()
                    await vector_store.ensure_collection(drop_existing=True)

            async with ConfluenceClient(settings) as confluence:
                last_ingest_iso: str | None = None
                use_cql = False

                # fill_gaps: find page IDs in Confluence that are absent from page_index
                if fill_gaps and conversation_store:
                    logger.info("fill_gaps mode: scanning Confluence for unindexed pages")
                    all_confluence_ids = await confluence.get_all_page_ids(space_keys)
                    existing_versions = await conversation_store.get_page_versions(list(all_confluence_ids))
                    existing_ids = set(existing_versions.keys())
                    missing_ids = sorted(all_confluence_ids - existing_ids)
                    logger.info(
                        "fill_gaps: %d total, %d indexed, %d missing",
                        len(all_confluence_ids), len(existing_ids), len(missing_ids),
                    )
                    estimated_total = len(missing_ids)
                    _update_progress("confluence", 0, estimated_total)
                    page_iter = confluence.iter_pages_by_ids(missing_ids)

                else:
                    # Determine if we can use CQL for server-side incremental filtering
                    if not full_refresh and conversation_store:
                        try:
                            last_ingest_iso = await conversation_store.get_last_ingest_time()
                        except Exception:
                            last_ingest_iso = None
                        if last_ingest_iso:
                            use_cql = True
                            logger.info("CQL incremental mode: fetching pages changed since %s", last_ingest_iso)

                    # Get estimated total page count for progress tracking
                    try:
                        if use_cql and last_ingest_iso:
                            since_dt = datetime.fromisoformat(last_ingest_iso)
                            estimated_total = await confluence.get_changed_page_count(
                                since=since_dt, space_keys=space_keys,
                            )
                            logger.info("CQL: %d pages changed since last ingestion", estimated_total)
                        else:
                            estimated_total = await confluence.get_page_count(space_keys=space_keys)
                    except Exception:
                        estimated_total = 0
                    _update_progress("confluence", 0, estimated_total)

                    # Choose page iterator: CQL (only changed) vs full scan
                    if use_cql and last_ingest_iso:
                        since_dt = datetime.fromisoformat(last_ingest_iso)
                        page_iter = confluence.iter_pages_changed_since(
                            since=since_dt, space_keys=space_keys,
                        )
                    else:
                        page_iter = confluence.iter_pages(space_keys=space_keys)

                # Pre-fetch page versions in batches to avoid N+1 queries
                # (skipped in CQL mode — server already filtered to changed pages)
                _version_cache: dict[str, str] = {}
                _page_buffer: list = []
                _BATCH_SIZE = 50

                async def _flush_version_cache(pages):
                    """Batch-fetch page versions for accumulated pages."""
                    if not pages or full_refresh or use_cql or not conversation_store:
                        return
                    page_ids = [p.page_id for p in pages]
                    versions = await conversation_store.get_page_versions(page_ids)
                    _version_cache.update(versions)

                page_index = 0
                async for page in page_iter:
                    page_index += 1
                    _update_progress("confluence", page_index, max(estimated_total, page_index), skipped)
                    # Accumulate pages and batch-fetch versions (non-CQL mode only)
                    if not full_refresh and not use_cql and conversation_store:
                        _page_buffer.append(page)
                        if len(_page_buffer) >= _BATCH_SIZE:
                            await _flush_version_cache(_page_buffer)
                            _page_buffer.clear()

                    try:
                        new_lm = page.last_modified.isoformat()

                        # Incremental skip — check stored version before embedding
                        # In CQL mode, server already filtered so we skip this check
                        if not full_refresh and not use_cql and conversation_store:
                            # Flush remaining buffer if this page isn't cached yet
                            if page.page_id not in _version_cache and _page_buffer:
                                await _flush_version_cache(_page_buffer)
                                _page_buffer.clear()
                            if _version_cache.get(page.page_id) == new_lm:
                                skipped += 1
                                logger.debug("Skipping unchanged page '%s'", page.title)
                                continue

                        plain_text = html_to_text(page.body_html)
                        if not plain_text.strip():
                            continue

                        raw_chunks = split_text(
                            plain_text,
                            chunk_size=settings.chunk_size,
                            chunk_overlap=settings.chunk_overlap,
                        )

                        doc_chunks = [
                            DocumentChunk(
                                chunk_id=f"{page.page_id}_{chunk.index}",
                                page_id=page.page_id,
                                title=page.title,
                                space_key=page.space_key,
                                space_name=page.space_name,
                                url=page.url,
                                text=chunk.text,
                                chunk_index=chunk.index,
                                total_chunks=len(raw_chunks),
                                last_modified=page.last_modified,
                                section_heading=chunk.section_heading,
                                labels=page.labels,
                                ancestor_titles=page.ancestor_titles,
                            )
                            for chunk in raw_chunks
                        ]
                        _enrich_chunks(doc_chunks, enabled=settings.contextual_chunking_enabled)

                        # Delete existing chunks before re-upserting (prevents duplicates)
                        await vector_store.delete_page(page.page_id)
                        vectors = await embed_service.embed_batch(
                            [c.text for c in doc_chunks]
                        )
                        await vector_store.upsert_chunks(doc_chunks, vectors)

                        # Entity extraction (Cognee-lite)
                        if entity_store and settings.entity_extraction_enabled:
                            try:
                                await entity_store.extract_and_store(page.page_id, plain_text)
                            except Exception as exc:
                                logger.warning("Entity extraction failed for '%s': %s", page.title, exc)

                        # Update page index — rollback vectors on failure
                        if conversation_store:
                            try:
                                await conversation_store.upsert_page_index(
                                    page.page_id, new_lm, len(doc_chunks), page.space_key
                                )
                                linked_ids = extract_confluence_links(page.body_html)
                                if linked_ids:
                                    await conversation_store.upsert_page_links(page.page_id, linked_ids)
                            except Exception as idx_exc:
                                logger.error("Page index update failed for '%s', rolling back vectors: %s", page.title, idx_exc)
                                await vector_store.delete_page(page.page_id)
                                raise

                        pages_processed += 1
                        chunks_indexed += len(doc_chunks)
                        logger.info("page_ingested", source="confluence", title=page.title, chunks=len(doc_chunks), page_id=page.page_id)

                    except Exception as exc:
                        err = f"Page {page.page_id} ({page.title}): {exc}"
                        logger.exception("page_ingest_failed", source="confluence", page_id=page.page_id, title=page.title, error=str(exc))
                        errors.append(err)

        except Exception as exc:
            logger.exception("ingestion_fatal", source="confluence", error=str(exc))
            errors.append(f"Fatal: {exc}")
        finally:
            _ingest_status["running"] = False
            _ingest_status["end_time"] = _utcnow()
            _ingest_status["last_result"] = {
                "pages_processed": pages_processed,
                "pages_skipped": skipped,
                "chunks_indexed": chunks_indexed,
                "errors": errors,
            }
            logger.info("ingestion_complete", source="confluence", mode="fill_gaps" if fill_gaps else ("cql" if use_cql else "full_scan"), pages=pages_processed, skipped=skipped, chunks=chunks_indexed, errors=len(errors))

            # Invalidate semantic cache after ingestion so stale answers aren't served
            if semantic_cache and pages_processed > 0:
                try:
                    await semantic_cache.invalidate()
                    logger.info("Semantic cache invalidated after Confluence ingestion")
                except Exception as exc:
                    logger.warning("Failed to invalidate semantic cache: %s", exc)

            if chunks_indexed > 0:
                try:
                    titles = await vector_store.list_titles()
                    refresh_spell_dictionary(titles)
                except Exception as exc:
                    logger.warning("Failed to refresh spell dictionary: %s", exc)
                vector_store.invalidate_bm25()


# ── IDE MCP Bridge — push-pages ───────────────────────────────────────────

async def _process_single_page(
    page_id: str,
    title: str,
    space_key: str,
    space_name: str,
    url: str,
    html_content: str,
    last_updated: str,
    labels: list[str],
    ancestor_titles: list[str],
    *,
    settings: Settings,
    embed_service: EmbeddingService,
    vector_store: VectorStore,
    conversation_store=None,
    entity_store=None,
) -> int:
    """Embed and upsert one page. Returns number of chunks indexed (0 = skipped/empty)."""
    plain_text = html_to_text(html_content) if "<" in html_content else html_content
    if not plain_text.strip():
        return 0

    try:
        last_mod = (
            datetime.fromisoformat(last_updated.replace("Z", "+00:00"))
            if last_updated
            else datetime.now(timezone.utc)
        )
    except ValueError:
        last_mod = datetime.now(timezone.utc)

    raw_chunks = split_text(plain_text, chunk_size=settings.chunk_size, chunk_overlap=settings.chunk_overlap)
    doc_chunks = [
        DocumentChunk(
            chunk_id=f"{page_id}_{chunk.index}",
            page_id=page_id,
            title=title,
            space_key=space_key,
            space_name=space_name,
            url=url,
            text=chunk.text,
            chunk_index=chunk.index,
            total_chunks=len(raw_chunks),
            last_modified=last_mod,
            section_heading=chunk.section_heading,
            labels=labels,
            ancestor_titles=ancestor_titles,
        )
        for chunk in raw_chunks
    ]
    _enrich_chunks(doc_chunks, enabled=settings.contextual_chunking_enabled)

    await vector_store.delete_page(page_id)
    vectors = await embed_service.embed_batch([c.text for c in doc_chunks])
    await vector_store.upsert_chunks(doc_chunks, vectors)

    if entity_store and settings.entity_extraction_enabled:
        try:
            await entity_store.extract_and_store(page_id, plain_text)
        except Exception as exc:
            logger.warning("Entity extraction failed for '%s': %s", title, exc)

    if conversation_store:
        try:
            await conversation_store.upsert_page_index(page_id, last_mod.isoformat(), len(doc_chunks), space_key)
            linked_ids = extract_confluence_links(html_content)
            if linked_ids:
                await conversation_store.upsert_page_links(page_id, linked_ids)
        except Exception as idx_exc:
            logger.error("Page index update failed for '%s', rolling back vectors: %s", title, idx_exc)
            await vector_store.delete_page(page_id)
            raise

    return len(doc_chunks)


async def _process_single_page_okf(
    page_payload: PushPagePayload,
    *,
    settings: Settings,
    embed_service: EmbeddingService,
    vector_store: VectorStore,
    okf_converter,
    okf_chunker,
    graph_enricher,
    page_index_rows: list[tuple[str, str]],
    conversation_store=None,
    entity_store=None,
) -> int:
    """OKF variant of _process_single_page.

    Pipeline: HTML → OKF Markdown (LLM) → section chunks → graph enrichment → embed → upsert.
    Falls back to standard chunking if OKF conversion fails after retries.
    Returns number of chunks indexed (0 = empty/skipped).
    """
    from app.models.document import ConfluencePage  # noqa: PLC0415

    # Build a ConfluencePage for the OKF converter
    try:
        last_mod = (
            datetime.fromisoformat(page_payload.last_updated.replace("Z", "+00:00"))
            if page_payload.last_updated
            else datetime.now(timezone.utc)
        )
    except ValueError:
        last_mod = datetime.now(timezone.utc)

    confluence_page = ConfluencePage(
        page_id=page_payload.page_id,
        title=page_payload.title,
        body_html=page_payload.html_content,
        space_key=page_payload.space_key,
        space_name=page_payload.space_name,
        url=page_payload.url,
        last_modified=last_mod,
        version=0,
        labels=page_payload.labels,
        ancestor_titles=page_payload.ancestor_titles,
    )

    # OKF conversion — falls back to standard chunking on failure
    cr = await okf_converter.convert_page(confluence_page)
    if cr.success and cr.okf_markdown:
        doc_chunks = okf_chunker.chunk(
            page_id=page_payload.page_id,
            okf_markdown=cr.okf_markdown,
            title=page_payload.title,
            space_key=page_payload.space_key,
            space_name=page_payload.space_name,
            url=page_payload.url,
            last_modified=last_mod,
            labels=page_payload.labels,
            ancestor_titles=page_payload.ancestor_titles,
        )
        source = "okf"
    else:
        # Fallback to standard chunking if LLM conversion fails
        logger.warning("OKF conversion failed for '%s', falling back to standard chunking", page_payload.title)
        return await _process_single_page(
            page_id=page_payload.page_id,
            title=page_payload.title,
            space_key=page_payload.space_key,
            space_name=page_payload.space_name,
            url=page_payload.url,
            html_content=page_payload.html_content,
            last_updated=page_payload.last_updated,
            labels=page_payload.labels,
            ancestor_titles=page_payload.ancestor_titles,
            settings=settings,
            embed_service=embed_service,
            vector_store=vector_store,
            conversation_store=conversation_store,
            entity_store=entity_store,
        )

    if not doc_chunks:
        return 0

    # Graph enrichment — extract [[ConceptName]] links and resolve to page IDs
    if page_index_rows:
        try:
            await graph_enricher.enrich_page(
                page_id=page_payload.page_id,
                okf_content=cr.okf_markdown,
                ancestor_titles=page_payload.ancestor_titles,
                page_index_rows=page_index_rows,
            )
        except Exception as exc:
            logger.warning("Graph enrichment failed for '%s': %s", page_payload.title, exc)

    # Embed and upsert
    await vector_store.delete_page(page_payload.page_id)
    vectors = await embed_service.embed_batch([c.text for c in doc_chunks])
    await vector_store.upsert_chunks(doc_chunks, vectors)

    if entity_store and settings.entity_extraction_enabled:
        try:
            plain_for_entities = html_to_text(page_payload.html_content)
            await entity_store.extract_and_store(page_payload.page_id, plain_for_entities)
        except Exception as exc:
            logger.warning("Entity extraction failed for '%s': %s", page_payload.title, exc)

    if conversation_store:
        try:
            await conversation_store.upsert_page_index(
                page_payload.page_id, last_mod.isoformat(), len(doc_chunks), page_payload.space_key
            )
            linked_ids = extract_confluence_links(page_payload.html_content)
            if linked_ids:
                await conversation_store.upsert_page_links(page_payload.page_id, linked_ids)
        except Exception as idx_exc:
            logger.error("Page index update failed for '%s', rolling back: %s", page_payload.title, idx_exc)
            await vector_store.delete_page(page_payload.page_id)
            raise

    logger.info(
        "page_ingested", source=source, title=page_payload.title,
        chunks=len(doc_chunks), page_id=page_payload.page_id,
        okf_duration_s=getattr(cr.stats, "duration_s", None),
    )
    return len(doc_chunks)


async def _ingest_pushed_pages(
    pages: list[PushPagePayload],
    full_refresh: bool,
    settings: Settings,
    use_okf: bool = False,
    conversation_store=None,
    semantic_cache: SemanticCache | None = None,
    entity_store: EntityStore | None = None,
) -> IngestResponse:
    """Process a batch of pre-fetched pages. Runs synchronously; caller awaits the result."""
    embed_service = EmbeddingService(settings)
    vector_store = VectorStore(settings)
    await vector_store.ensure_collection(drop_existing=False)

    pages_processed = 0
    chunks_indexed = 0
    errors: list[str] = []

    # Initialise OKF pipeline components (only when requested)
    okf_converter = okf_chunker_inst = graph_enricher = None
    page_index_rows: list[tuple[str, str]] = []
    if use_okf:
        from app.services.okf_converter import OKFConverter  # noqa: PLC0415
        from app.services.okf_chunker import OKFAwareChunker  # noqa: PLC0415
        from app.services.graph_enricher import EnhancedGraphEnricher  # noqa: PLC0415
        okf_converter = OKFConverter(settings)
        okf_chunker_inst = OKFAwareChunker()
        graph_enricher = EnhancedGraphEnricher(conversation_store) if conversation_store else None
        # Pre-fetch all (page_id, title) pairs for concept resolution
        page_index_rows = await vector_store.list_page_id_title_pairs()
        logger.info("OKF mode: loaded %d page-title pairs for concept resolution", len(page_index_rows))

    for page in pages:
        try:
            if use_okf and okf_converter and okf_chunker_inst:
                n = await _process_single_page_okf(
                    page,
                    settings=settings,
                    embed_service=embed_service,
                    vector_store=vector_store,
                    okf_converter=okf_converter,
                    okf_chunker=okf_chunker_inst,
                    graph_enricher=graph_enricher,
                    page_index_rows=page_index_rows,
                    conversation_store=conversation_store,
                    entity_store=entity_store,
                )
            else:
                n = await _process_single_page(
                    page_id=page.page_id,
                    title=page.title,
                    space_key=page.space_key,
                    space_name=page.space_name,
                    url=page.url,
                    html_content=page.html_content,
                    last_updated=page.last_updated,
                    labels=page.labels,
                    ancestor_titles=page.ancestor_titles,
                    settings=settings,
                    embed_service=embed_service,
                    vector_store=vector_store,
                    conversation_store=conversation_store,
                    entity_store=entity_store,
                )
            if n > 0:
                pages_processed += 1
                chunks_indexed += n
        except Exception as exc:
            err = f"Page {page.page_id} ({page.title}): {exc}"
            logger.warning("page_ingest_failed", source="ide_mcp", title=page.title, error=str(exc))
            errors.append(err)

    if semantic_cache and pages_processed > 0:
        try:
            await semantic_cache.invalidate()
            logger.info("Semantic cache invalidated after push-pages ingest")
        except Exception as exc:
            logger.warning("Failed to invalidate semantic cache: %s", exc)

    if chunks_indexed > 0:
        try:
            titles = await vector_store.list_titles()
            refresh_spell_dictionary(titles)
        except Exception as exc:
            logger.warning("Failed to refresh spell dictionary: %s", exc)
        vector_store.invalidate_bm25()

    return IngestResponse(
        status="ok",
        pages_processed=pages_processed,
        chunks_indexed=chunks_indexed,
        errors=errors,
    )


@router.post("/push-pages", response_model=IngestResponse, status_code=status.HTTP_200_OK)
async def push_pages(
    request_body: PushPagesRequest,
    request: Request,
    settings: Settings = Depends(get_settings),
    _auth: None = Depends(verify_api_key),
):
    """IDE MCP Bridge — push pre-fetched Confluence pages directly into Assistant Bot.

    Use this endpoint when you have page HTML from an external source (e.g. an
    IDE tool or script) and want to index it without Assistant Bot
    fetching from Confluence itself.  Runs synchronously and returns the full result.

    Recommended: ≤ 50 pages per request.  For full-space ingest, use POST /api/ingest.
    """
    if not request_body.pages:
        return IngestResponse(status="ok", pages_processed=0, chunks_indexed=0, errors=[])

    store = request.app.state.conversation_store
    semantic_cache = request.app.state.pipeline.semantic_cache
    entity_store = getattr(request.app.state, "entity_store", None)

    logger.info(
        "push_pages_start",
        count=len(request_body.pages),
        full_refresh=request_body.full_refresh,
        use_okf=request_body.use_okf,
    )
    return await _ingest_pushed_pages(
        pages=request_body.pages,
        full_refresh=request_body.full_refresh,
        use_okf=request_body.use_okf,
        settings=settings,
        conversation_store=store,
        semantic_cache=semantic_cache,
        entity_store=entity_store,
    )


# ── Jira Ingestion ────────────────────────────────────────────────────────

@router.post("/jira", response_model=IngestResponse, status_code=status.HTTP_202_ACCEPTED)
async def trigger_jira_ingest(
    request_body: JiraIngestRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    settings: Settings = Depends(get_settings),
    _auth: None = Depends(verify_api_key),
):
    """Ingest Jira issues into Qdrant for RAG search."""
    if not settings.jira_enabled:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Jira integration not enabled. Set JIRA_ENABLED=true in .env.")
    if _ingest_status["running"]:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Ingestion is already running.")

    semantic_cache = request.app.state.pipeline.semantic_cache
    background_tasks.add_task(
        _run_jira_ingestion,
        settings=settings,
        project_keys=request_body.project_keys,
        full_refresh=request_body.full_refresh,
        semantic_cache=semantic_cache,
    )
    return IngestResponse(status="accepted", pages_processed=0, chunks_indexed=0, errors=[])


async def _run_jira_ingestion(
    settings: Settings,
    project_keys: list[str] | None,
    full_refresh: bool,
    semantic_cache: SemanticCache | None = None,
) -> None:
    async with _ingest_lock:
        _ingest_status["running"] = True
        _ingest_status["start_time"] = _utcnow()
        _ingest_status["end_time"] = None
        _update_progress("jira", 0, 0)
        issues_processed = 0
        chunks_indexed = 0
        errors: list[str] = []

        embed_service = EmbeddingService(settings)
        vector_store = VectorStore(settings)

        try:
            await vector_store.ensure_collection(drop_existing=False)

            async with JiraClient(settings) as jira:
                issue_index = 0
                async for issue in jira.iter_issues(project_keys=project_keys):
                    issue_index += 1
                    _update_progress("jira", issue_index, 0)  # total unknown for streaming
                    try:
                        doc_chunks = issue_to_chunks(issue)
                        if not doc_chunks:
                            continue
                        _enrich_chunks(doc_chunks, enabled=settings.contextual_chunking_enabled)

                        for chunk in doc_chunks:
                            if full_refresh or True:  # Always upsert (idempotent)
                                await vector_store.delete_page(chunk.page_id)

                        vectors = await embed_service.embed_batch([c.text for c in doc_chunks])
                        await vector_store.upsert_chunks(doc_chunks, vectors)

                        issues_processed += 1
                        chunks_indexed += len(doc_chunks)

                        if issues_processed % 50 == 0:
                            logger.info("jira_ingest_progress", issues=issues_processed, chunks=chunks_indexed)

                    except Exception as exc:
                        key = issue.get("key", "unknown")
                        logger.warning("jira_issue_ingest_failed", key=key, error=str(exc))
                        errors.append(f"{key}: {exc}")

        except Exception as exc:
            logger.exception("jira_ingestion_fatal", error=str(exc))
            errors.append(f"Fatal: {exc}")
        finally:
            _ingest_status["running"] = False
            _ingest_status["end_time"] = _utcnow()
            _ingest_status["last_result"] = {
                "source": "jira",
                "pages_processed": issues_processed,
                "chunks_indexed": chunks_indexed,
                "errors": errors,
            }
            logger.info("ingestion_complete", source="jira", issues=issues_processed, chunks=chunks_indexed, errors=len(errors))

            if semantic_cache and issues_processed > 0:
                try:
                    await semantic_cache.invalidate()
                except Exception:
                    pass

            if chunks_indexed > 0:
                try:
                    titles = await vector_store.list_titles()
                    refresh_spell_dictionary(titles)
                except Exception:
                    pass
                vector_store.invalidate_bm25()


# ── GitHub Ingestion ──────────────────────────────────────────────────────

@router.post("/github", response_model=IngestResponse, status_code=status.HTTP_202_ACCEPTED)
async def trigger_github_ingest(
    request_body: GitHubIngestRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    settings: Settings = Depends(get_settings),
    _auth: None = Depends(verify_api_key),
):
    """Ingest GitHub repo files and PRs into Qdrant for RAG search."""
    if not settings.github_enabled:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="GitHub integration not enabled. Set GITHUB_ENABLED=true in .env.")
    if _ingest_status["running"]:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Ingestion is already running.")

    semantic_cache = request.app.state.pipeline.semantic_cache
    background_tasks.add_task(
        _run_github_ingestion,
        settings=settings,
        repos=request_body.repos,
        include_prs=request_body.include_prs,
        full_refresh=request_body.full_refresh,
        semantic_cache=semantic_cache,
    )
    return IngestResponse(status="accepted", pages_processed=0, chunks_indexed=0, errors=[])


async def _run_github_ingestion(
    settings: Settings,
    repos: list[str] | None,
    include_prs: bool,
    full_refresh: bool,
    semantic_cache: SemanticCache | None = None,
) -> None:
    async with _ingest_lock:
        _ingest_status["running"] = True
        _ingest_status["start_time"] = _utcnow()
        _ingest_status["end_time"] = None
        _update_progress("github", 0, 0)
        files_processed = 0
        prs_processed = 0
        chunks_indexed = 0
        errors: list[str] = []

        embed_service = EmbeddingService(settings)
        vector_store = VectorStore(settings)

        try:
            await vector_store.ensure_collection(drop_existing=False)
            target_repos = repos or settings.github_repos

            async with GitHubClient(settings) as gh:
                for repo in target_repos:
                    # Ingest repo files
                    file_index = 0
                    async for file_meta in gh.iter_repo_files(repo):
                        file_index += 1
                        _update_progress("github", files_processed + prs_processed, 0)
                        try:
                            content = await gh.get_file_content(repo, file_meta["path"])
                            if not content or not content.strip():
                                continue

                            chunk = file_to_chunk(repo, file_meta["path"], content)
                            _enrich_chunks([chunk], enabled=settings.contextual_chunking_enabled)
                            await vector_store.delete_page(chunk.page_id)
                            vectors = await embed_service.embed_batch([chunk.text])
                            await vector_store.upsert_chunks([chunk], vectors)

                            files_processed += 1
                            chunks_indexed += 1

                            if files_processed % 50 == 0:
                                logger.info("github_file_ingest_progress", repo=repo, files=files_processed)

                        except Exception as exc:
                            path = file_meta.get("path", "unknown")
                            logger.warning("github_file_ingest_failed", repo=repo, path=path, error=str(exc))
                            errors.append(f"{repo}/{path}: {exc}")

                    # Ingest PRs
                    if include_prs:
                        async for pr_data in gh.iter_recent_prs(repo, limit=50):
                            try:
                                chunk = pr_to_chunk(repo, pr_data)
                                if not chunk:
                                    continue

                                _enrich_chunks([chunk], enabled=settings.contextual_chunking_enabled)
                                await vector_store.delete_page(chunk.page_id)
                                vectors = await embed_service.embed_batch([chunk.text])
                                await vector_store.upsert_chunks([chunk], vectors)

                                prs_processed += 1
                                chunks_indexed += 1

                            except Exception as exc:
                                pr_num = pr_data.get("number", "?")
                                logger.warning("github_pr_ingest_failed", repo=repo, pr=pr_num, error=str(exc))
                                errors.append(f"{repo}/PR#{pr_num}: {exc}")

        except Exception as exc:
            logger.exception("github_ingestion_fatal", error=str(exc))
            errors.append(f"Fatal: {exc}")
        finally:
            _ingest_status["running"] = False
            _ingest_status["end_time"] = _utcnow()
            _ingest_status["last_result"] = {
                "source": "github",
                "files_processed": files_processed,
                "prs_processed": prs_processed,
                "pages_processed": files_processed + prs_processed,
                "chunks_indexed": chunks_indexed,
                "errors": errors,
            }
            logger.info("ingestion_complete", source="github", files=files_processed, prs=prs_processed, chunks=chunks_indexed, errors=len(errors))

            if semantic_cache and (files_processed + prs_processed) > 0:
                try:
                    await semantic_cache.invalidate()
                except Exception:
                    pass

            if chunks_indexed > 0:
                try:
                    titles = await vector_store.list_titles()
                    refresh_spell_dictionary(titles)
                except Exception:
                    pass
                vector_store.invalidate_bm25()
