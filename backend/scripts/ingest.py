"""
Standalone ingestion script — run outside the container for local testing.

Usage:
    cd backend
    pip install -r requirements.txt
    python -m scripts.ingest --spaces ENG HR --full-refresh
"""
from __future__ import annotations
import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import Settings
from app.services.confluence import ConfluenceClient
from app.services.embeddings import EmbeddingService
from app.services.vector_store import VectorStore
from app.utils.html_parser import html_to_text
from app.utils.text_splitter import split_text
from app.models.document import DocumentChunk

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("ingest")


async def run_ingestion(
    settings: Settings,
    space_keys: list[str] | None = None,
    full_refresh: bool = False,
) -> None:
    embed_service = EmbeddingService(settings)
    vector_store = VectorStore(settings)

    logger.info("Ensuring Qdrant collection (full_refresh=%s)", full_refresh)
    await vector_store.ensure_collection(drop_existing=full_refresh)

    total_pages = 0
    total_chunks = 0
    errors: list[str] = []

    async with ConfluenceClient(settings) as confluence:
        spaces = space_keys or settings.confluence_space_keys
        logger.info("Ingesting spaces: %s", spaces)

        async for page in confluence.iter_pages(space_keys=spaces):
            try:
                plain_text = html_to_text(page.body_html)
                if not plain_text.strip():
                    logger.debug("Skipping empty page: %s", page.title)
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
                    )
                    for chunk in raw_chunks
                ]

                vectors = await embed_service.embed_batch([c.text for c in doc_chunks])
                await vector_store.upsert_chunks(doc_chunks, vectors)

                total_pages += 1
                total_chunks += len(doc_chunks)
                logger.info("✓ %s (%d chunks)", page.title, len(doc_chunks))

            except Exception as exc:
                err = f"Page {page.page_id} ({page.title}): {exc}"
                logger.warning("Error: %s", err)
                errors.append(err)

    logger.info(
        "\n─── Ingestion complete ───\n"
        "  Pages  : %d\n"
        "  Chunks : %d\n"
        "  Errors : %d\n",
        total_pages, total_chunks, len(errors),
    )
    if errors:
        logger.warning("Errors:\n  " + "\n  ".join(errors))


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest Confluence pages into Qdrant")
    parser.add_argument("--spaces", nargs="*", help="Space keys (default: from .env)")
    parser.add_argument("--full-refresh", action="store_true", help="Drop and re-index all data")
    args = parser.parse_args()

    settings = Settings()
    asyncio.run(run_ingestion(settings, space_keys=args.spaces, full_refresh=args.full_refresh))


if __name__ == "__main__":
    main()
