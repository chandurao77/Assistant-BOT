"""Upload endpoint — session-scoped file upload for Q&A."""
from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, status

from app.api.dependencies import verify_api_key
from app.config import get_settings, Settings
from app.models.document import DocumentChunk
from app.services.file_parser import (
    ALLOWED_EXTENSIONS,
    MAX_FILE_SIZE,
    allowed_extension,
    parse_file,
)
from app.utils.text_splitter import split_text
from datetime import datetime, timezone

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/upload", tags=["upload"], dependencies=[Depends(verify_api_key)])


@router.post("")
async def upload_file(
    file: UploadFile,
    request: Request,
    conversation_id: str | None = None,
    settings: Settings = Depends(get_settings),
):
    """
    Upload a file for session-scoped Q&A. The file is parsed, chunked, embedded,
    and stored in Qdrant with an ``__UPLOAD__`` space key so it can be merged
    with Confluence results during retrieval.

    - Max file size: 10 MB
    - Supported formats: .txt, .md, .pdf, .docx
    - Chunks are tagged with ``upload_id`` for later cleanup
    """
    # Validate filename
    if not file.filename or not allowed_extension(file.filename):
        exts = ", ".join(sorted(ALLOWED_EXTENSIONS.keys()))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type. Allowed: {exts}",
        )

    # Read and validate size
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum size is {MAX_FILE_SIZE // (1024 * 1024)} MB.",
        )
    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File is empty.",
        )

    # Validate file content matches extension (magic byte check)
    ext = file.filename.rsplit(".", 1)[-1].lower() if file.filename else ""
    _MAGIC_BYTES = {
        "pdf": b"%PDF",
        "docx": b"PK\x03\x04",   # ZIP-based Office format
        "pptx": b"PK\x03\x04",
    }
    expected_magic = _MAGIC_BYTES.get(ext)
    if expected_magic and not content[:4].startswith(expected_magic):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File content does not match .{ext} format.",
        )

    # Parse text from file
    try:
        text = parse_file(file.filename, content)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )

    # Generate identifiers
    upload_id = str(uuid.uuid4())
    page_id = f"upload_{upload_id}"
    conv_id = conversation_id or str(uuid.uuid4())
    title = file.filename

    # Chunk the text
    raw_chunks = split_text(
        text,
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
    )
    if not raw_chunks:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Could not extract any meaningful text from file.",
        )

    doc_chunks = [
        DocumentChunk(
            chunk_id=f"{page_id}_{c.index}",
            page_id=page_id,
            title=title,
            space_key="__UPLOAD__",
            space_name="Uploaded Files",
            url="",
            text=c.text,
            chunk_index=c.index,
            total_chunks=len(raw_chunks),
            last_modified=datetime.now(timezone.utc),
            section_heading=c.section_heading,
        )
        for c in raw_chunks
    ]

    # Contextual enrichment
    if settings.contextual_chunking_enabled:
        for chunk in doc_chunks:
            chunk.enrich_text()

    # Embed and store
    pipeline = request.app.state.pipeline
    vectors = await pipeline.embeddings.embed_batch([c.text for c in doc_chunks])
    await pipeline.vector_store.upsert_chunks(doc_chunks, vectors)

    # Invalidate semantic cache so new content is used immediately
    semantic_cache = getattr(request.app.state, "semantic_cache", None)
    if semantic_cache:
        await semantic_cache.invalidate()

    logger.info(
        "Uploaded file '%s' → %d chunks (upload_id=%s, conversation_id=%s)",
        title, len(doc_chunks), upload_id, conv_id,
    )

    return {
        "status": "ok",
        "upload_id": upload_id,
        "filename": title,
        "chunks": len(doc_chunks),
        "conversation_id": conv_id,
    }


@router.delete("/{upload_id}")
async def delete_upload(upload_id: str, request: Request):
    """Remove all chunks for a specific upload from Qdrant."""
    pipeline = request.app.state.pipeline
    page_id = f"upload_{upload_id}"
    await pipeline.vector_store.delete_page(page_id)
    logger.info("Deleted upload chunks for upload_id=%s", upload_id)
    return {"status": "ok", "upload_id": upload_id}
