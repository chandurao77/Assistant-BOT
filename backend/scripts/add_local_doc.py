"""
Add a local document (plain text) to the Qdrant knowledge base.

Supports two modes:
  --sections   (default) Section-aware: splits on blank lines, detects headings,
               and creates one chunk per section with the heading prefixed.
               Best for structured docs like checklists and guides.
  --raw        Uses the standard text splitter (word-based chunking).

Usage (inside container):
    python -m scripts.add_local_doc --file docs/new_engineer_checklist.txt \
        --title "New Engineer Checklist" --space LOCAL

Usage (standalone — needs QDRANT_HOST=localhost in env):
    python -m scripts.add_local_doc --file docs/my_doc.txt --title "My Doc"
"""
from __future__ import annotations
import argparse
import asyncio
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import Settings
from app.services.embeddings import EmbeddingService
from app.services.vector_store import VectorStore
from app.utils.text_splitter import split_text
from app.models.document import DocumentChunk

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("add_local_doc")


def _split_into_sections(text: str, doc_title: str) -> list[tuple[str, str]]:
    """
    Split text into sections using blank-line boundaries.

    Returns a list of (section_title, section_text) tuples.
    Each section is prefixed with its heading for better embeddings.
    """
    # Split on double newlines (blank lines)
    blocks = re.split(r"\n\s*\n", text.strip())

    sections: list[tuple[str, str]] = []
    current_heading = doc_title
    current_body: list[str] = []

    for block in blocks:
        block = block.strip()
        if not block:
            continue

        lines = block.split("\n")
        first_line = lines[0].strip()

        # Detect if this block starts with a heading (short line, no URLs, title-case like)
        is_heading = (
            len(first_line.split()) <= 10
            and "http" not in first_line.lower()
            and not first_line.startswith("-")
            and not first_line.startswith("*")
        )

        if is_heading and len(lines) == 1:
            # Flush previous section
            if current_body:
                body_text = " ".join(current_body)
                sections.append((current_heading, f"{current_heading}: {body_text}"))
                current_body = []
            current_heading = first_line
        elif is_heading and len(lines) > 1:
            # Heading + body in same block
            if current_body:
                body_text = " ".join(current_body)
                sections.append((current_heading, f"{current_heading}: {body_text}"))
                current_body = []
            current_heading = first_line
            current_body.append(" ".join(line.strip() for line in lines[1:]))
        else:
            # Body content
            current_body.append(" ".join(line.strip() for line in lines))

    # Flush last section
    if current_body:
        body_text = " ".join(current_body)
        sections.append((current_heading, f"{current_heading}: {body_text}"))

    return sections


async def add_document(
    file_path: str,
    title: str,
    space_key: str = "LOCAL",
    space_name: str = "Local Documents",
    page_id: str | None = None,
    chunk_size: int | None = None,
    use_sections: bool = True,
) -> None:
    settings = Settings()
    if chunk_size is None:
        chunk_size = settings.chunk_size
    embed_service = EmbeddingService(settings)
    vector_store = VectorStore(settings)

    text = Path(file_path).read_text(encoding="utf-8")
    if not text.strip():
        logger.error("File is empty: %s", file_path)
        return

    # Use filename as page_id if not provided
    if not page_id:
        page_id = f"local_{Path(file_path).stem}"

    if use_sections:
        # Section-aware splitting — one chunk per topic section.
        # Each section gets a unique page_id so the vector store's
        # per-page de-duplication doesn't collapse them into one result.
        sections = _split_into_sections(text, title)
        logger.info("Split '%s' into %d sections", title, len(sections))
        doc_chunks = [
            DocumentChunk(
                chunk_id=f"{page_id}_{i}",
                page_id=f"{page_id}_{i}",
                title=f"{section_title} - {title}",
                space_key=space_key,
                space_name=space_name,
                url="",
                text=section_text,
                chunk_index=0,
                total_chunks=1,
                last_modified=datetime.now(timezone.utc),
            )
            for i, (section_title, section_text) in enumerate(sections)
        ]
    else:
        # Standard word-based chunking
        raw_chunks = split_text(text, chunk_size=chunk_size, chunk_overlap=settings.chunk_overlap)
        logger.info("Split '%s' into %d chunks", title, len(raw_chunks))
        doc_chunks = [
            DocumentChunk(
                chunk_id=f"{page_id}_{chunk.index}",
                page_id=page_id,
                title=title,
                space_key=space_key,
                space_name=space_name,
                url="",
                text=chunk.text,
                chunk_index=chunk.index,
                total_chunks=len(raw_chunks),
                last_modified=datetime.now(timezone.utc),
            )
            for chunk in raw_chunks
        ]

    # Embed all chunks
    texts = [c.text for c in doc_chunks]
    vectors = await embed_service.embed_batch(texts)
    logger.info("Generated %d embeddings", len(vectors))

    # Ensure collection exists (won't drop existing)
    await vector_store.ensure_collection(drop_existing=False)

    # Delete old version of this page (if re-ingesting)
    # Delete both the base page_id and any section-split page_ids (page_id_0, page_id_1, ...)
    await vector_store.delete_page(page_id)
    if use_sections:
        from qdrant_client import models as qmodels
        await vector_store._client.delete(
            collection_name=vector_store._collection,
            points_selector=qmodels.FilterSelector(
                filter=qmodels.Filter(
                    must=[qmodels.FieldCondition(
                        key="page_id",
                        match=qmodels.MatchText(text=page_id),
                    )]
                )
            ),
        )

    # Upsert
    await vector_store.upsert_chunks(doc_chunks, vectors)
    logger.info("✓ Ingested '%s' (%d chunks) into space '%s'", title, len(doc_chunks), space_key)


def main() -> None:
    parser = argparse.ArgumentParser(description="Add a local document to Qdrant")
    parser.add_argument("--file", required=True, help="Path to the text file")
    parser.add_argument("--title", required=True, help="Document title")
    parser.add_argument("--space", default="LOCAL", help="Space key (default: LOCAL)")
    parser.add_argument("--space-name", default="Local Documents", help="Space name")
    parser.add_argument("--page-id", default=None, help="Custom page ID")
    parser.add_argument("--chunk-size", type=int, default=None, help="Override chunk size (words)")
    parser.add_argument("--raw", action="store_true", help="Use raw word-based chunking instead of section-aware splitting")
    args = parser.parse_args()

    asyncio.run(add_document(
        file_path=args.file,
        title=args.title,
        space_key=args.space,
        space_name=args.space_name,
        page_id=args.page_id,
        chunk_size=args.chunk_size,
        use_sections=not args.raw,
    ))


if __name__ == "__main__":
    main()
