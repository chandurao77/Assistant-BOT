"""Feedback endpoint — stores per-message ratings and triggers self-learning."""
from __future__ import annotations
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, Request, status
from pydantic import BaseModel, Field
from typing import Literal

from app.api.dependencies import get_optional_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/feedback", tags=["feedback"])

# Valid reason codes for negative feedback
NegativeReason = Literal[
    "outdated_information",
    "wrong_answer",
    "incomplete_answer",
    "not_relevant",
    "other",
]


class FeedbackRequest(BaseModel):
    message_id: str = Field(description="Frontend UUID of the assistant message")
    conversation_id: str
    value: int = Field(description="+1 for helpful, -1 for not helpful", ge=-1, le=1)
    reason: NegativeReason | None = Field(default=None, description="Reason code (required for thumbs-down)")
    reason_text: str | None = Field(default=None, max_length=500, description="Free-text detail (for 'other' reason)")
    source_page_ids: list[str] | None = Field(default=None, description="Confluence page IDs from cited sources (for auto-reingest)")


@router.post("", status_code=status.HTTP_204_NO_CONTENT)
async def submit_feedback(
    body: FeedbackRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    user: dict | None = Depends(get_optional_user),
):
    """Record user feedback for an assistant message.

    On +1 (thumbs-up) the matching Q\u2019A pair is also indexed in Qdrant so
    future semantically-similar questions surface this verified answer.

    On -1 (thumbs-down) any previously-learned Q&A entry for this message
    is removed from Qdrant to prevent bad answers from resurfacing.

    Self-learning (Qdrant indexing) is only performed when the user is
    authenticated, to prevent anonymous feedback poisoning.
    """
    if body.value == 0:
        return
    store = request.app.state.conversation_store
    await store.save_feedback(
        body.message_id, body.conversation_id, body.value,
        reason=body.reason, reason_text=body.reason_text,
    )

    pipeline = request.app.state.pipeline

    # Self-learning: positive feedback → index the Q&A into Qdrant
    # Only allowed for authenticated users to prevent feedback poisoning
    if body.value == 1 and user:
        try:
            messages = await store.get_conversation_messages(body.conversation_id)
            if messages:
                for i, msg in enumerate(messages):
                    if msg["id"] == body.message_id and i > 0:
                        prev = messages[i - 1]
                        if prev["role"] == "user":
                            q_vector = await pipeline.embeddings.embed(prev["content"])
                            await pipeline.vector_store.index_qa_pair(
                                message_id=body.message_id,
                                question=prev["content"],
                                answer=msg["content"],
                                question_vector=q_vector,
                            )
                        break
        except Exception as exc:  # noqa: BLE001
            logger.warning("Self-learn indexing failed (non-critical): %s", exc)

    # Negative feedback → remove any previously-learned Q&A for this message
    elif body.value == -1 and user:
        try:
            await pipeline.vector_store.remove_learned_qa(body.message_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to remove learned Q&A (non-critical): %s", exc)

        # Auto-reingest: if reason is "outdated_information", re-ingest the
        # source Confluence pages that were cited in this answer.
        if body.reason == "outdated_information" and body.source_page_ids:
            try:
                # Filter to only Confluence page IDs (exclude __JIRA__, __GITHUB__ etc.)
                confluence_page_ids = [
                    pid for pid in body.source_page_ids
                    if not pid.startswith(("jira_", "github_", "upload_", "learned_"))
                ]
                if confluence_page_ids:
                    settings = request.app.state.settings
                    background_tasks.add_task(
                        _reingest_pages,
                        page_ids=confluence_page_ids,
                        settings=settings,
                        store=store,
                    )
                    logger.info(
                        "Auto-reingest triggered for %d source pages (feedback: outdated_information)",
                        len(confluence_page_ids),
                    )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Auto-reingest setup failed (non-critical): %s", exc)


@router.get("/stats")
async def feedback_stats(request: Request):
    """Return aggregate feedback metrics for the analytics dashboard."""
    store = request.app.state.conversation_store
    stats = await store.get_feedback_stats()
    return stats


# ── Auto-reingest helpers ──────────────────────────────────────────────────


async def _reingest_pages(
    page_ids: list[str],
    settings,
    store,
) -> None:
    """Re-ingest specific Confluence pages in the background.

    Tries Flow MCP first (if enabled), falls back to direct Confluence API.
    Each page is fetched fresh, re-embedded, and upserted to Qdrant.
    """
    from app.services.embeddings import EmbeddingService
    from app.services.vector_store import VectorStore
    from app.utils.html_parser import html_to_text
    from app.utils.text_splitter import split_text
    from app.models.document import DocumentChunk

    embed_service = EmbeddingService(settings)
    vector_store = VectorStore(settings)
    await vector_store.ensure_collection()

    reingested = 0
    for page_id in page_ids[:5]:  # Cap at 5 pages per feedback event
        try:
            page = await _fetch_page(page_id, settings)
            if not page:
                logger.warning("Auto-reingest: page %s not found, skipping", page_id)
                continue

            plain = html_to_text(page["body"]) if "<" in page.get("body", "") else page.get("body", "")
            if not plain.strip():
                continue

            raw_chunks = split_text(plain, chunk_size=settings.chunk_size, chunk_overlap=settings.chunk_overlap)
            doc_chunks = [
                DocumentChunk(
                    chunk_id=f"{page_id}_{c.index}",
                    page_id=page_id,
                    title=page.get("title", ""),
                    space_key=page.get("space_key", ""),
                    space_name=page.get("space_name", ""),
                    url=page.get("url", ""),
                    text=c.text,
                    chunk_index=c.index,
                    total_chunks=len(raw_chunks),
                )
            for c in raw_chunks
            ]

            await vector_store.delete_page(page_id)
            vectors = await embed_service.embed_batch([c.text for c in doc_chunks])
            await vector_store.upsert_chunks(doc_chunks, vectors)

            if store:
                try:
                    from datetime import datetime, timezone
                    await store.upsert_page_index(page_id, datetime.now(timezone.utc).isoformat(), len(doc_chunks))
                except Exception:
                    pass

            reingested += 1
            logger.info("Auto-reingest: page %s updated (%d chunks)", page_id, len(doc_chunks))

        except Exception as exc:
            logger.warning("Auto-reingest failed for page %s: %s", page_id, exc)

    logger.info("Auto-reingest complete: %d/%d pages refreshed", reingested, len(page_ids))


async def _fetch_page(page_id: str, settings) -> dict | None:
    """Fetch a single page by ID via the Confluence API."""
    try:
        from app.services.confluence import ConfluenceClient
        async with ConfluenceClient(settings) as client:
            page = await client.get_page_by_id(page_id)
            if page:
                return {
                    "body": page.body_html,
                    "title": page.title,
                    "space_key": page.space_key,
                    "space_name": page.space_name,
                    "url": page.url,
                }
    except Exception as exc:
        logger.warning("Direct Confluence fetch failed for %s: %s", page_id, exc)

    return None
