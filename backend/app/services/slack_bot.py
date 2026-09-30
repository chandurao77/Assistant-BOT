"""Slack bot service — bridges Slack events to the Assistant Bot RAG pipeline."""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time

from app.config import Settings

logger = logging.getLogger(__name__)


def verify_slack_signature(
    body: bytes,
    timestamp: str,
    signature: str,
    signing_secret: str,
) -> bool:
    """Verify that a request genuinely came from Slack using HMAC-SHA256."""
    if not signing_secret or not signature or not timestamp:
        return False
    # Reject requests older than 5 minutes (replay protection)
    if abs(time.time() - int(timestamp)) > 300:
        return False
    sig_basestring = f"v0:{timestamp}:{body.decode('utf-8')}"
    computed = "v0=" + hmac.new(
        signing_secret.encode("utf-8"),
        sig_basestring.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(computed, signature)


async def run_rag_query(
    question: str,
    pipeline,
    conversation_store,
    user_id: str | None = None,
    conversation_id: str | None = None,
) -> dict:
    """
    Run a question through the RAG pipeline and collect the full answer + sources.

    Returns ``{"answer": str, "sources": list[dict], "conversation_id": str}``.
    """
    import uuid

    cid = conversation_id or str(uuid.uuid4())

    # Load history for multi-turn
    raw_history = await conversation_store.get_history(cid)
    history = raw_history[-12:] if raw_history else None

    corrected_question, _ = await pipeline.prepare_query(question)

    answer_tokens: list[str] = []
    sources_list: list[dict] = []

    async for token, sources in pipeline.stream(
        corrected_question,
        history=history,
        request_id=cid,
        conversation_store=conversation_store,
    ):
        if sources is not None:
            sources_list = [
                {
                    "title": s.title,
                    "url": s.url,
                    "space": s.space_key,
                    "score": round(s.score, 3),
                }
                for s in sources
            ]
        elif token:
            answer_tokens.append(token)

    full_answer = "".join(answer_tokens)

    # Persist the turn
    user_msg_id = str(uuid.uuid4())
    assistant_msg_id = str(uuid.uuid4())
    await conversation_store.append_turn(
        cid,
        title=question[:60].strip(),
        user_content=question,
        assistant_content=full_answer,
        user_msg_id=user_msg_id,
        assistant_msg_id=assistant_msg_id,
        user_id=user_id,
    )

    return {
        "answer": full_answer,
        "sources": sources_list,
        "conversation_id": cid,
    }


def format_slack_response(result: dict, include_sources: bool = True) -> list[dict]:
    """Format a RAG result into Slack Block Kit blocks."""
    blocks: list[dict] = []

    # Answer text
    blocks.append({
        "type": "section",
        "text": {"type": "mrkdwn", "text": result["answer"][:3000]},
    })

    # Sources
    if include_sources and result["sources"]:
        source_lines = []
        for s in result["sources"][:5]:
            if s.get("url"):
                source_lines.append(f"• <{s['url']}|{s['title']}> (score: {s['score']})")
            else:
                source_lines.append(f"• {s['title']} (score: {s['score']})")
        blocks.append({"type": "divider"})
        blocks.append({
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": "*Sources:*\n" + "\n".join(source_lines)}],
        })

    return blocks
