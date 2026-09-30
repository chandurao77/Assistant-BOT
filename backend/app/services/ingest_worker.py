"""
Async ingestion worker — runs as a separate process/container.

Reads ingestion jobs from a Redis queue and processes them independently
from the API server. This prevents long Confluence syncs from blocking
HTTP requests.

Usage:
    # As a standalone process:
    python -m app.services.ingest_worker

    # As a container service:
    podman compose --profile worker up -d

    # Queue a job from the API:
    POST /api/ingest  →  pushes job to Redis queue  →  worker picks it up
"""
from __future__ import annotations

import asyncio
import json
import logging
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path

import structlog

logger = structlog.get_logger(__name__)

# Redis key for the ingestion job queue
INGEST_QUEUE_KEY = "assistant_bot:ingest:jobs"
INGEST_STATUS_KEY = "assistant_bot:ingest:status"


async def process_job(job: dict) -> dict:
    """Process a single ingestion job."""
    from app.config import get_settings
    from app.services.embeddings import EmbeddingService
    from app.services.vector_store import VectorStore
    from app.services.confluence import ConfluenceClient
    from app.services.local_loader import load_local_docs
    from app.utils.html_parser import html_to_text, extract_confluence_links
    from app.utils.text_splitter import split_text
    from app.models.document import DocumentChunk

    settings = get_settings()
    embed_service = EmbeddingService(settings)
    vector_store = VectorStore(settings)
    await vector_store.ensure_collection(drop_existing=job.get("full_refresh", False))

    space_keys = job.get("space_keys") or settings.confluence_space_keys
    source = job.get("source", "confluence")
    pages_processed = 0
    chunks_indexed = 0
    errors: list[str] = []

    if source == "local":
        docs_dir = Path(job.get("docs_dir", "/app/test_docs"))
        pages = load_local_docs(docs_dir) if docs_dir.exists() else []
        for page in pages:
            try:
                plain = html_to_text(page.body_html) if "<" in page.body_html else page.body_html
                if not plain.strip():
                    continue
                raw_chunks = split_text(plain, chunk_size=settings.chunk_size, chunk_overlap=settings.chunk_overlap)
                doc_chunks = [
                    DocumentChunk(
                        chunk_id=f"{page.page_id}_{c.index}", page_id=page.page_id,
                        title=page.title, space_key=page.space_key, space_name=page.space_name,
                        url=page.url, text=c.text, chunk_index=c.index,
                        total_chunks=len(raw_chunks), last_modified=page.last_modified,
                    )
                    for c in raw_chunks
                ]
                vectors = await embed_service.embed_batch([c.text for c in doc_chunks])
                await vector_store.upsert_chunks(doc_chunks, vectors)
                pages_processed += 1
                chunks_indexed += len(doc_chunks)
            except Exception as exc:
                errors.append(f"Page {page.page_id}: {exc}")
    else:
        # Confluence ingestion
        if not settings.confluence_base_url or not settings.confluence_api_token:
            return {"status": "error", "error": "Confluence credentials not configured"}

        client = ConfluenceClient(settings)
        for space_key in space_keys:
            try:
                pages = await client.get_pages(space_key, limit=settings.confluence_page_limit)
                for page in pages:
                    try:
                        plain = html_to_text(page.body_html)
                        if not plain.strip():
                            continue
                        raw_chunks = split_text(plain, chunk_size=settings.chunk_size, chunk_overlap=settings.chunk_overlap)
                        doc_chunks = [
                            DocumentChunk(
                                chunk_id=f"{page.page_id}_{c.index}", page_id=page.page_id,
                                title=page.title, space_key=page.space_key, space_name=page.space_name,
                                url=page.url, text=c.text, chunk_index=c.index,
                                total_chunks=len(raw_chunks), last_modified=page.last_modified,
                            )
                            for c in raw_chunks
                        ]
                        vectors = await embed_service.embed_batch([c.text for c in doc_chunks])
                        await vector_store.upsert_chunks(doc_chunks, vectors)
                        pages_processed += 1
                        chunks_indexed += len(doc_chunks)
                    except Exception as exc:
                        errors.append(f"Page {page.page_id}: {exc}")
            except Exception as exc:
                errors.append(f"Space {space_key}: {exc}")

    return {
        "status": "completed",
        "pages_processed": pages_processed,
        "chunks_indexed": chunks_indexed,
        "errors": errors,
        "finished_at": datetime.now(timezone.utc).isoformat(),
    }


async def worker_loop() -> None:
    """Main worker loop — polls Redis for ingestion jobs."""
    import redis.asyncio as aioredis
    from app.config import get_settings

    settings = get_settings()
    redis_url = settings.redis_url if settings.redis_enabled else "redis://redis:6379/0"

    logger.info("Ingestion worker starting", redis_url=redis_url)
    redis = aioredis.from_url(redis_url, decode_responses=True)

    # Graceful shutdown
    shutdown = asyncio.Event()

    def _signal_handler(*_):
        logger.info("Shutdown signal received")
        shutdown.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            asyncio.get_event_loop().add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            signal.signal(sig, _signal_handler)

    logger.info("Ingestion worker ready — waiting for jobs on %s", INGEST_QUEUE_KEY)

    while not shutdown.is_set():
        try:
            # Blocking pop with 5s timeout
            result = await redis.blpop(INGEST_QUEUE_KEY, timeout=5)
            if result is None:
                continue

            _, raw_job = result
            job = json.loads(raw_job)
            job_id = job.get("id", "unknown")

            logger.info("Processing ingestion job", job_id=job_id)
            await redis.set(INGEST_STATUS_KEY, json.dumps({
                "running": True,
                "job_id": job_id,
                "started_at": datetime.now(timezone.utc).isoformat(),
            }))

            result = await process_job(job)

            await redis.set(INGEST_STATUS_KEY, json.dumps({
                "running": False,
                "job_id": job_id,
                "last_result": result,
            }))
            logger.info("Job completed", job_id=job_id, pages=result.get("pages_processed", 0))

        except Exception as exc:
            logger.error("Worker error", error=str(exc))
            await asyncio.sleep(5)

    await redis.close()
    logger.info("Ingestion worker stopped")


if __name__ == "__main__":
    logging.basicConfig(level="INFO")
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ],
        logger_factory=structlog.PrintLoggerFactory(),
    )
    asyncio.run(worker_loop())
