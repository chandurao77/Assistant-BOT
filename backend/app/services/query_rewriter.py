"""Query rewriter — expands vague questions into better retrieval queries.

Uses a fast LLM call to rephrase short/vague questions into keyword-rich
queries that embed closer to relevant documents. Only rewrites when a
heuristic detects the question is too vague for direct embedding search.

Enterprise pattern: the rewritten query runs in PARALLEL with the original,
and results are merged — so a bad rewrite can never hurt retrieval quality.
"""
from __future__ import annotations
import asyncio
import json
import logging
import re
from typing import Any

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)

# ── Heuristic: should we rewrite? ─────────────────────────────────────────
_MIN_WORD_COUNT = 7  # Questions with >= 7 words are usually specific enough
_SPECIFIC_NOUN_PATTERNS = [
    r"[A-Z]{2,10}-\d+",       # Jira ticket (MESH-123)
    r"\b[A-Z][a-z]+[A-Z]\w+",  # CamelCase identifiers
    r"\b\w+\.\w+\.\w+",        # dotted paths (app.services.rag)
    r"\b\w+_\w+_\w+",          # snake_case with 3+ parts
]

# Hardcoded prompt — NOT configurable to prevent prompt manipulation
_REWRITE_SYSTEM_PROMPT = """\
You are a search query optimizer. Given a user's question, rewrite it into a \
better search query that will find relevant documents in a knowledge base.

Rules:
1. Expand vague terms into specific keywords and synonyms.
2. Keep the original intent — do NOT change what the user is asking.
3. Output ONLY the rewritten query, nothing else. No explanation, no quotes.
4. Keep it concise — aim for 10-20 words.
5. Include the key nouns and technical terms from the original question.
"""


def needs_rewrite(question: str) -> bool:
    """Fast heuristic to decide if a question is too vague for direct search.

    Returns True only for short, vague questions without specific identifiers.
    """
    words = question.split()
    # Long questions are usually specific enough
    if len(words) >= _MIN_WORD_COUNT:
        return False
    # Questions with specific identifiers (ticket IDs, code paths) don't need rewriting
    for pattern in _SPECIFIC_NOUN_PATTERNS:
        if re.search(pattern, question):
            return False
    return True


async def rewrite_query(question: str, settings: Settings) -> str | None:
    """Rewrite a vague question into a better search query.

    Returns the rewritten query string, or None if rewriting fails or is skipped.
    Uses the same LLM provider configured for the main pipeline.
    """
    if not needs_rewrite(question):
        return None

    try:
        return await _rewrite_ollama(question, settings)
    except Exception as exc:
        logger.warning("Query rewrite failed (non-fatal): %s", exc)
        return None


async def _rewrite_ollama(question: str, settings: Settings) -> str | None:
    """Rewrite via the local Ollama server."""
    url = f"{settings.ollama_base_url.rstrip('/')}/api/chat"
    payload = {
        "model": settings.ollama_llm_model,
        "messages": [
            {"role": "system", "content": _REWRITE_SYSTEM_PROMPT},
            {"role": "user", "content": question},
        ],
        "stream": False,
        "options": {"temperature": 0.1, "num_predict": 60},
    }
    timeout = httpx.Timeout(connect=5, read=30, write=5, pool=5)
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()
        rewritten = data.get("message", {}).get("content", "").strip()
        if rewritten and rewritten != question:
            logger.info("Query rewritten: %r -> %r", question, rewritten)
            return rewritten
    return None
