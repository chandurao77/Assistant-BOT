"""
Cross-encoder re-ranking using the LLM.

After vector retrieval, re-scores each source chunk by asking the LLM
to rate relevance (0-10) of each chunk to the question. This is more
accurate than bi-encoder similarity because the question and chunk are
encoded jointly.

Uses Ollama's /api/generate endpoint with a short scoring prompt to keep
latency low. Falls back gracefully to the original ranking on errors.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re

import httpx

from app.config import Settings
from app.models.document import classify_page_type
from app.models.schemas import SourceDocument

logger = logging.getLogger(__name__)

_RERANK_PROMPT = """\
Does this document directly answer or provide substantial information about the question?
Reply with exactly one word: YES, PARTIAL, or NO.

- YES = the document is primarily about this topic or directly answers the question
- PARTIAL = the document mentions the topic but is mainly about something else
- NO = the document does not meaningfully address the question

Question: {question}

Document: {text}

Answer:"""

# Map LLM response to numeric scores
_SCORE_MAP = {"YES": 9.0, "PARTIAL": 5.0, "NO": 2.0}


def _answer_presence_bonus(question: str, text: str) -> float:
    """Return 0.20 if the chunk text appears to contain an actual answer to the question type.

    Heuristic checks based on question word:
    - HOW  → chunk has steps, instructions, numbered lists, or imperative verbs
    - WHAT → chunk has definitions ("is a", "refers to", "means", "defined as")
    - WHERE → chunk has location indicators ("located", "found in", "in the")
    - WHEN → chunk has temporal info ("date", year patterns, "after", "before")
    - WHO  → chunk has person/role references ("responsible", "owner", "team")
    - General → chunk has a sentence that restates key query nouns
    """
    q_lower = question.strip().lower()
    t_lower = text.lower()

    # Detect question type from first word
    q_type = None
    for prefix in ("how ", "what ", "where ", "when ", "who ", "why "):
        if q_lower.startswith(prefix):
            q_type = prefix.strip()
            break

    if q_type == "how":
        # Look for instructional patterns
        patterns = [
            r"\b(step\s*\d|first[,.]?\s|then\s|next[,.]?\s|finally\s)",
            r"\b(to set up|to configure|to install|to create|to enable|to request)",
            r"\b(run the|execute|navigate to|click on|open the|go to)",
            r"^\s*\d+[\.\)]\s",  # numbered list items
        ]
        for pat in patterns:
            if re.search(pat, t_lower, re.MULTILINE):
                return 0.20
    elif q_type == "what":
        patterns = [
            r"\bis\s+(?:a|an|the)\s+\w+",
            r"\brefers?\s+to\b",
            r"\bmeans?\b",
            r"\bdefined?\s+as\b",
            r"\bprovides?\b.*\bfor\b",
            r"\bis\s+used\s+(?:to|for)\b",
        ]
        for pat in patterns:
            if re.search(pat, t_lower):
                return 0.20
    elif q_type == "where":
        patterns = [r"\blocated\b", r"\bfound\s+in\b", r"\bunder\s+the\b", r"\bin\s+the\s+\w+\s+(directory|folder|page|section|tab)"]
        for pat in patterns:
            if re.search(pat, t_lower):
                return 0.20
    elif q_type == "when":
        patterns = [r"\b\d{4}[-/]\d{2}\b", r"\b(after|before|during|since)\s", r"\b(date|deadline|schedule)\b"]
        for pat in patterns:
            if re.search(pat, t_lower):
                return 0.20
    elif q_type == "who":
        patterns = [r"\b(responsible|owner|team|contact|assigned)\b", r"\b(managed by|maintained by|created by)\b"]
        for pat in patterns:
            if re.search(pat, t_lower):
                return 0.20

    # Fallback: check if key query nouns appear in a sentence-like context
    # (not just mentioned in a list or header)
    q_nouns = set(w.lower() for w in re.findall(r"\b\w{4,}\b", question))
    q_nouns -= {"what", "how", "where", "when", "does", "this", "that", "about",
                "tell", "explain", "describe", "please", "help", "need"}
    if q_nouns:
        # Check if 2+ query nouns appear in the same sentence
        sentences = re.split(r"[.!?\n]", t_lower)
        for sent in sentences:
            hits = sum(1 for n in q_nouns if n in sent)
            if hits >= 2 and len(sent.split()) >= 5:
                return 0.15
    return 0.0


# Score adjustments per page type (+boost or -penalty applied to final display score)
_PAGE_TYPE_ADJUSTMENT = {
    "howto":     0.05,   # small boost — already gets answer_presence bonus
    "reference": 0.05,   # small boost — technical docs are useful
    "report":   -0.25,   # penalty — status/release pages rarely answer questions (was -0.20)
    "general":   0.00,   # neutral
}

# Label-based adjustments (Confluence page labels stored at ingest time)
_LABEL_PENALTY = {"deprecated", "archived", "outdated", "old", "legacy", "obsolete"}
_LABEL_BOOST   = {"official", "canonical", "approved", "recommended"}


def _label_adjustment(labels: list[str]) -> float:
    """Return a score delta based on Confluence page labels.

    - deprecated/archived/outdated → −0.15 (stale content, unlikely to be correct)
    - official/canonical/approved  → +0.05 (authoritative source)
    - Penalties take priority: a deprecated+canonical page is still penalized.
    """
    lower = {lbl.lower() for lbl in labels}
    if lower & _LABEL_PENALTY:
        return -0.15
    if lower & _LABEL_BOOST:
        return 0.05
    return 0.0


def _keyword_relevance(question: str, text: str) -> float:
    """Score 0.0-1.0 based on how many question keywords appear in the text.

    Combines keyword hit ratio with density (occurrences per 100 words).
    Applies a penalty when the most specific query terms are missing.
    """
    # Extract meaningful words (3+ chars, lowercased)
    q_words = set(w.lower() for w in re.findall(r"\b\w{3,}\b", question))
    stop_words = {
        # Common English stop words that add no search value
        "the", "about", "tell", "what", "how", "does", "this", "that", "with",
        "from", "have", "are", "was", "for", "can", "you", "please", "give",
        "information", "details", "explain", "describe", "overview", "know",
        "like", "would", "could", "should", "there", "their", "they", "than",
        "then", "when", "where", "which", "who", "whom", "will", "your",
        "been", "being", "some", "such", "each", "every", "more", "most",
        "other", "into", "also", "just", "only", "very", "much", "many",
        "any", "all", "both", "few", "own", "same", "still", "well",
        "using", "used", "use", "get", "got", "getting", "need", "needs",
        "want", "wants", "make", "made", "way", "ways",
    }
    # Generic words that match many documents — low signal
    generic_words = {
        "application", "app", "system", "service", "tool", "platform",
        "org", "team", "project", "process", "server", "api", "setup",
        "environment", "config", "configuration", "document", "page",
    }
    q_words -= stop_words
    if not q_words:
        return 0.5

    # Separate specific terms (high signal) from generic ones
    specific_words = q_words - generic_words

    text_lower = text.lower()
    text_words = re.findall(r"\b\w{3,}\b", text_lower)
    total_words = max(len(text_words), 1)

    # Check if specific terms appear at all — if none do, heavy penalty
    specific_hits = sum(1 for w in specific_words if w in text_lower) if specific_words else 0
    if specific_words and specific_hits == 0:
        # The most important query terms are completely absent
        return 0.05

    # Hit ratio: what fraction of ALL query terms appear?
    all_hits = sum(1 for w in q_words if w in text_lower)
    hit_ratio = all_hits / len(q_words)

    # Density: how often do query terms appear per 100 words?
    occurrences = sum(text_lower.count(w) for w in q_words)
    density = min(occurrences / (total_words / 100), 10.0) / 10.0  # cap at 1.0

    # Exact phrase bonus: if consecutive query words appear together
    phrase_bonus = 0.0
    q_specific_list = sorted(specific_words, key=lambda w: question.lower().find(w))
    if len(q_specific_list) >= 2:
        # Check for 2-word phrases from the query in the text
        for i in range(len(q_specific_list) - 1):
            bigram = q_specific_list[i] + " " + q_specific_list[i + 1]
            if bigram in text_lower:
                phrase_bonus = 0.2
                break

    base_score = 0.6 * hit_ratio + 0.4 * density
    return min(base_score + phrase_bonus, 1.0)


class Reranker:
    """LLM-based cross-encoder re-ranker using Ollama."""

    def __init__(self, settings: Settings) -> None:
        self._enabled = settings.rerank_enabled
        self._top_n = settings.rerank_top_n
        self._url = f"{settings.ollama_base_url.rstrip('/')}/api/generate"
        self._model = settings.ollama_rerank_model or settings.ollama_llm_model
        # Short read timeout — if Ollama can't score in 3s it's under load; fall back fast
        self._timeout = httpx.Timeout(connect=5, read=3, write=5, pool=5)
        self._semaphore = asyncio.Semaphore(2)  # M5 Metal can handle 2 concurrent rerank calls
        # Max LLM candidates: only score the top-N by initial vector score to bound latency
        self._llm_candidates = min(settings.rerank_top_n, 8)
        # Persistent HTTP client — reused across requests
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self._timeout)
        return self._client

    async def close(self) -> None:
        """Close the persistent HTTP client. Called during app shutdown."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def rerank(
        self,
        question: str,
        sources: list[SourceDocument],
    ) -> list[SourceDocument]:
        """Update display scores on sources using LLM cross-encoder + keyword + vector.

        Scoring formula:
          0.40 * llm_score (YES/PARTIAL/NO → 1.0/0.55/0.22) +
          0.35 * vector_score +
          0.15 * keyword_score +
          answer_bonus(0.20) + title_boost(0.15) + type_adj + label_adj

        LLM scoring runs concurrently (capped by semaphore) and falls back to
        heuristic-only scoring per source if Ollama is unavailable or times out.
        """
        if not self._enabled or len(sources) <= 1:
            return sources

        # Extract specific query terms for title boost
        q_all = set(w.lower() for w in re.findall(r"\b\w{3,}\b", question))
        _stop = {
            "the", "about", "tell", "what", "how", "does", "this", "that", "with",
            "from", "have", "are", "was", "for", "can", "you", "please", "give",
            "information", "details", "explain", "describe", "overview", "know",
            "like", "would", "could", "should", "there", "their", "using", "used",
        }
        _generic = {
            "application", "app", "system", "service", "tool", "platform",
            "org", "team", "project", "process", "server", "api", "setup",
            "environment", "config", "configuration",
        }
        specific_terms = q_all - _stop - _generic

        # LLM cross-encoder: only score top candidates by initial vector score.
        # This bounds worst-case latency to _llm_candidates × read_timeout (6s each).
        # Sources beyond that cap get the neutral PARTIAL score (5.0) from heuristics.
        sorted_by_vector = sorted(range(len(sources)), key=lambda i: sources[i].score, reverse=True)
        llm_candidate_indices = set(sorted_by_vector[: self._llm_candidates])

        llm_scores: list[float] = [5.0] * len(sources)  # default: PARTIAL
        timeout_count = 0
        try:
            client = await self._get_client()
            for i in sorted_by_vector[: self._llm_candidates]:
                # Early-abort: if first candidate timed out, Ollama is saturated — skip all
                if timeout_count >= 1:
                    logger.warning(
                        "Reranker: Ollama timeout — skipping LLM scoring for remaining %d sources",
                        self._llm_candidates - i - 1,
                    )
                    break
                score = await self._score_one(client, question, sources[i])
                if score == 3.0:  # 3.0 is the timeout/error fallback in _score_one
                    timeout_count += 1
                else:
                    timeout_count = 0  # reset on success
                llm_scores[i] = score
        except Exception as exc:
            logger.warning("LLM reranking batch failed, using heuristics only: %s", exc)

        for src, raw_llm in zip(sources, llm_scores):
            text = (src.content or src.excerpt) or ""
            title_text = (src.title or "") + " " + text
            kw_score = _keyword_relevance(question, title_text)

            # Answer-presence bonus
            answer_bonus = _answer_presence_bonus(question, text)

            # Title match boost
            title_lower = (src.title or "").lower()
            title_boost = 0.0
            if specific_terms:
                title_hits = sum(1 for t in specific_terms if t in title_lower)
                title_boost = 0.15 * (title_hits / len(specific_terms))

            # Page type and label adjustments
            page_type = src.page_type or classify_page_type(src.title or "")
            type_adj = _PAGE_TYPE_ADJUSTMENT[page_type]
            label_adj = _label_adjustment(src.labels or [])

            # Normalize LLM score from 0-10 range to 0-1
            # YES=9.0 → 1.0, PARTIAL=5.0 → 0.55, NO=2.0 → 0.22
            llm_normalized = raw_llm / 9.0

            # Combined: 40% LLM + 35% vector + 15% keyword + bonuses
            display_score = min(
                0.40 * llm_normalized
                + 0.35 * src.score
                + 0.15 * kw_score
                + answer_bonus
                + title_boost
                + type_adj
                + label_adj,
                1.0,
            )
            src.score = round(max(display_score, 0.0), 4)

        logger.info(
            "Reranked %d sources (LLM+heuristic): top=%.3f, min=%.3f",
            len(sources),
            max(s.score for s in sources),
            min(s.score for s in sources),
        )

        return sources

    async def _score_one(
        self,
        client: httpx.AsyncClient,
        question: str,
        source: SourceDocument,
    ) -> float:
        """Score a single source against the question."""
        async with self._semaphore:
            text = (source.content or source.excerpt)[:500]
            prompt = _RERANK_PROMPT.format(question=question, text=text)
            try:
                resp = await client.post(
                    self._url,
                    json={
                        "model": self._model,
                        "prompt": prompt,
                        "stream": False,
                        "options": {"temperature": 0.0, "num_predict": 8},
                    },
                )
                raw = resp.json().get("response", "").strip().upper()
                # Match YES/PARTIAL/NO from response
                for key, score in _SCORE_MAP.items():
                    if key in raw:
                        return score
                # If the model returned a number, try parsing it
                match = re.search(r"\b(\d+(?:\.\d+)?)\b", raw)
                if match:
                    return min(float(match.group(1)), 10.0)
            except Exception as exc:
                logger.debug("Rerank scoring failed for '%s': %s", source.title[:40], exc)
            # Fallback: assign a low score so failed-to-score sources don't dominate
            return 3.0
