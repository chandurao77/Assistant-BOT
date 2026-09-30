"""
Local ingestion script — test the full RAG pipeline without Confluence.

Reads documents from a local folder and indexes them into Qdrant.

Usage:
    python -m scripts.ingest_local                          # uses ./test_docs/
    python -m scripts.ingest_local --docs path/to/folder   # custom folder
    python -m scripts.ingest_local --full-refresh           # drop + re-index
"""
from __future__ import annotations
import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import os
os.environ.setdefault("CONFLUENCE_BASE_URL", "http://localhost")
os.environ.setdefault("CONFLUENCE_EMAIL", "local@test.com")
os.environ.setdefault("CONFLUENCE_API_TOKEN", "local-test-token")

from app.config import Settings
from app.services.local_loader import load_local_docs
from app.services.embeddings import EmbeddingService
from app.services.vector_store import VectorStore
from app.utils.html_parser import html_to_text
from app.utils.text_splitter import split_text
from app.models.document import DocumentChunk

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("local-ingest")


async def run(docs_dir: Path, full_refresh: bool) -> None:
    settings = Settings()

    logger.info("Loading documents from: %s", docs_dir.resolve())
    pages = load_local_docs(docs_dir)

    if not pages:
        logger.error("No documents found. Add .txt, .md, or .json files to: %s", docs_dir)
        return

    embed_service = EmbeddingService(settings)
    vector_store = VectorStore(settings)

    await vector_store.ensure_collection(drop_existing=full_refresh)

    total_chunks = 0
    errors: list[str] = []

    for page in pages:
        try:
            # html_to_text handles plain text gracefully
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
                )
                for c in raw_chunks
            ]

            vectors = await embed_service.embed_batch([c.text for c in doc_chunks])
            await vector_store.upsert_chunks(doc_chunks, vectors)
            total_chunks += len(doc_chunks)
            logger.info("  ✓ %-45s → %d chunk(s)", page.title[:45], len(doc_chunks))

        except Exception as exc:
            errors.append(f"{page.title}: {exc}")
            logger.warning("  ✗ %s — %s", page.title, exc)

    count = await vector_store.count()
    print(f"\n{'─'*50}")
    print(f"  Documents : {len(pages)}")
    print(f"  Chunks    : {total_chunks}")
    print(f"  Errors    : {len(errors)}")
    print(f"  Qdrant    : {count} total vectors in collection")
    print(f"{'─'*50}")
    print(f"\n  ✅ Ready! Open http://localhost:3000 and ask questions.\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest local documents into Qdrant")
    parser.add_argument("--docs", default="test_docs", help="Folder containing .txt/.md/.json files")
    parser.add_argument("--full-refresh", action="store_true", help="Drop and rebuild the index")
    args = parser.parse_args()
    asyncio.run(run(Path(args.docs), args.full_refresh))


if __name__ == "__main__":
    main()
