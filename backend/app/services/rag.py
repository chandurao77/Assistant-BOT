"""
RAG (Retrieval-Augmented Generation) pipeline.

Orchestrates: embed question → retrieve chunks → stream LLM answer
"""
from __future__ import annotations
import asyncio
import logging
import re
from typing import AsyncIterator

from app.config import Settings
from app.models.schemas import SourceDocument
from app.services.embeddings import EmbeddingService
from app.services.vector_store import VectorStore
from app.services.llm import LLMService
from app.services.semantic_cache import SemanticCache
from app.services.content_guardrail import ContentGuardrail
from app.services.entity_store import EntityStore
from app.services.reranker import Reranker
from app.services.intent_router import classify_intent
from app.services.query_rewriter import rewrite_query, needs_rewrite
from app.services.bm25 import tokenize as bm25_tokenize

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from app.services.redis_cache import RedisCache

logger = logging.getLogger(__name__)

# ── Corpus-only spell correction ─────────────────────────────────────────
# Instead of using a general English dictionary (which "corrects" valid
# product/project names to random English words), we build a vocabulary
# exclusively from ingested content.  Unknown words are left as-is — the
# embedding model handles minor typos better than a wrong correction.
#
# The _corpus_vocab set holds lowercase words extracted from page titles
# during ingestion.  A base set of common tech terms is included so the
# spell checker works even before the first ingestion run.

_BASE_TECH_WORDS: set[str] = {
    "assistant", "onboarding", "offboarding", "devops", "microservice", "microservices",
    "kubernetes", "dockerfile", "backend", "frontend", "fullstack",
    "webhook", "webhooks", "middleware", "signup", "login", "logout",
    "repo", "repos", "runbook", "runbooks", "rollback", "rollbacks",
    "cicd", "hackathon", "standup", "standups", "retro", "retros",
    "okr", "okrs", "kpi", "kpis", "sla", "slas", "vpc", "vpcs",
    "saml", "oauth", "sso", "ldap", "rbac", "iam", "mfa",
    "ansible", "terraform", "grafana", "elasticsearch", "kibana",
    "datadog", "splunk", "jira", "confluence", "bitbucket", "github",
    "gitlab", "jenkins", "bamboo", "artifactory", "sonarqube",
    "qdrant", "ollama", "langchain", "fastapi", "uvicorn", "nginx",
    "redis", "kafka", "rabbitmq", "postgres", "postgresql", "mongodb",
    "swimlane", "swimlanes", "blocker", "blockers", "deprioritize",
    "codebase", "refactor", "refactoring", "linting", "linter",
    "roadmap", "roadmaps", "timeline", "timelines", "workflow", "workflows",
    "escalation", "escalations", "provisioning", "deprovisioning",
}

# Corpus vocabulary — grows as content is ingested
_corpus_vocab: set[str] = set(_BASE_TECH_WORDS)


def refresh_spell_dictionary(titles: list[str]) -> int:
    """
    Extract unique words from ingested document titles and add them to the
    corpus vocabulary.  Called after each ingestion run so the spell
    corrector can suggest domain-specific corrections.

    Returns the number of new words added.
    """
    words: set[str] = set()
    for title in titles:
        for token in re.split(r'[^a-zA-Z]+', title):
            if len(token) >= 3:
                words.add(token.lower())
    before = len(_corpus_vocab)
    _corpus_vocab.update(words)
    added = len(_corpus_vocab) - before
    if added:
        logger.info("Spell dictionary refreshed: +%d words from %d titles (vocab size: %d)", added, len(titles), len(_corpus_vocab))
    return added


def _edit_distance_1(word: str) -> set[str]:
    """Generate all strings that are 1 edit distance from ``word``."""
    letters = 'abcdefghijklmnopqrstuvwxyz'
    splits = [(word[:i], word[i:]) for i in range(len(word) + 1)]
    deletes = [L + R[1:] for L, R in splits if R]
    transposes = [L + R[1] + R[0] + R[2:] for L, R in splits if len(R) > 1]
    replaces = [L + c + R[1:] for L, R in splits if R for c in letters]
    inserts = [L + c + R for L, R in splits for c in letters]
    return set(deletes + transposes + replaces + inserts)


def _correct_question(question: str) -> str:
    """
    Corpus-only spell correction for enterprise search queries.

    Key design decisions:
    - Only corrects TO words that exist in the corpus vocabulary (ingested
      content + base tech terms).  Never corrects to random English words.
    - Unknown words with no corpus match are left as-is — the embedding
      model handles minor typos via semantic similarity.
    - Skips short words (<4 chars), acronyms (uppercase), and proper nouns.
    - Max edit distance of 1 — prevents aggressive corrections.
    """
    corrected_words = []
    for word in question.split():
        stripped = word.rstrip('.,!?;:')
        suffix = word[len(stripped):]
        # Only attempt correction on lowercase alpha words of 4+ chars
        if stripped.isalpha() and stripped.islower() and len(stripped) >= 4:
            # Already known in corpus — keep as-is
            if stripped in _corpus_vocab:
                corrected_words.append(word)
                continue
            # Find corpus-only candidates at edit distance 1
            candidates = _edit_distance_1(stripped) & _corpus_vocab
            if candidates:
                # Pick the candidate with highest frequency in corpus
                # (for now, just pick the shortest edit — most are single-char fixes)
                fix = min(candidates, key=lambda c: (abs(len(c) - len(stripped)), c))
                logger.debug("Spell correction: %r -> %r (from corpus)", stripped, fix)
                corrected_words.append(fix + suffix)
                continue
        corrected_words.append(word)
    return ' '.join(corrected_words)

_NO_CONTEXT_REPLY = (
    "I could not find any relevant information in the knowledge base "
    "(Confluence, Jira, or GitHub) to answer your question. Please try "
    "rephrasing, or check if the relevant content has been ingested."
)


class RAGPipeline:
    """
    Full RAG pipeline:
    1. Embed the user question
    2. Retrieve top-k relevant chunks from Qdrant
    3. Stream the LLM answer conditioned on retrieved context
    4. Yield sources after the answer is complete
    """

    def __init__(self, settings: Settings, redis_cache: "RedisCache | None" = None) -> None:
        self._settings = settings
        self.embeddings = EmbeddingService(settings, redis_cache=redis_cache)
        self.vector_store = VectorStore(settings)
        self.llm = LLMService(settings)
        self.semantic_cache = SemanticCache(settings, redis_cache=redis_cache)
        self.content_guardrail = ContentGuardrail(settings)
        self.reranker = Reranker(settings)

    async def prepare_query(self, question: str) -> tuple[str, str | None]:
        """
        Spell-correct the question before retrieval.
        Returns ``(corrected_question, original_if_changed)``.
        If no correction was needed the second element is ``None``.
        """
        corrected = _correct_question(question)
        if corrected != question:
            logger.info("Query corrected: %r -> %r", question, corrected)
            return corrected, question
        return question, None

    async def _expand_with_links(
        self,
        sources: list[SourceDocument],
        conversation_store,
    ) -> list[SourceDocument]:
        """
        One-hop graph expansion: fetch chunks from pages linked by the retrieved sources.

        Two link sources are combined:
        1. ``page_links`` table — Confluence ``<a>`` href links (existing GraphRAG).
        2. ``related_concepts`` Qdrant payload field — OKF semantic [[ConceptName]] links
           written to ``page_links`` by EnhancedGraphEnricher at ingest time.

        Both are already stored in the same ``page_links`` table so no extra query is needed.
        Capped at ``settings.graph_max_expansion`` additional pages.
        """
        source_page_ids = [s.page_id for s in sources]
        linked_ids = await conversation_store.get_linked_page_ids(source_page_ids)
        if not linked_ids:
            return sources
        linked_ids = linked_ids[: self._settings.graph_max_expansion]
        extra = await self.vector_store.fetch_by_page_ids(linked_ids)
        if extra:
            logger.info("Graph expansion: +%d linked pages", len(extra))
        return sources + extra

    async def _retrieve(
        self,
        question: str,
        query_vector: list[float],
        space_keys: list[str] | None,
        rewrite_task,
        entity_store: EntityStore | None,
        conversation_store,
        rid: str,
    ) -> list[SourceDocument]:
        """Steps 2a–2d: search, merge rewrites, entity boost, graph expand, re-rank."""
        # 2. Intent routing
        effective_keys = space_keys
        intent = classify_intent(question)
        if not effective_keys:
            effective_keys = intent.space_key_filters
        if intent.matched_source:
            logger.info("[%s] Intent router → %s (confidence=%.2f)", rid, intent.matched_source, intent.confidence)

        # 2a. Search with original query
        sources = await self.vector_store.search(
            query_vector=query_vector,
            top_k=self._settings.retrieval_top_k,
            score_threshold=self._settings.retrieval_score_threshold,
            space_keys=effective_keys,
            query_text=question,
        )
        logger.info("[%s] Retrieved %d source documents (original query)", rid, len(sources))

        # 2b. Merge results from rewritten query (if available)
        if rewrite_task:
            rewritten = await rewrite_task
            if rewritten:
                logger.info("[%s] Rewritten query: %r", rid, rewritten)
                rewrite_vector = await self.embeddings.embed(rewritten)
                rewrite_sources = await self.vector_store.search(
                    query_vector=rewrite_vector,
                    top_k=self._settings.retrieval_top_k,
                    score_threshold=self._settings.retrieval_score_threshold,
                    space_keys=effective_keys,
                    query_text=rewritten,
                )
                existing_ids = {(s.page_id, s.excerpt[:100]) for s in sources}
                new_sources = [s for s in rewrite_sources if (s.page_id, s.excerpt[:100]) not in existing_ids]
                if new_sources:
                    sources.extend(new_sources)
                    logger.info("[%s] Query rewrite added %d new sources (total: %d)", rid, len(new_sources), len(sources))

        # 2c. Entity boosting (Cognee-lite)
        if entity_store and self._settings.entity_extraction_enabled:
            try:
                boosted_ids = await entity_store.find_pages_by_entities(question)
                existing_ids = {s.page_id for s in sources}
                new_ids = [pid for pid in boosted_ids if pid not in existing_ids]
                if new_ids:
                    entity_sources = await self.vector_store.fetch_by_page_ids(new_ids[:4])
                    if entity_sources:
                        sources.extend(entity_sources)
                        logger.info("[%s] Entity boost: +%d pages from entity matching", rid, len(entity_sources))
            except Exception as exc:
                logger.warning("[%s] Entity boost failed: %s", rid, exc)

        # 2d. Graph expansion
        if sources and self._settings.graph_hop_depth > 0 and conversation_store is not None:
            sources = await self._expand_with_links(sources, conversation_store)
            logger.info("[%s] After graph expansion: %d source documents", rid, len(sources))

        if not sources:
            return []

        # 2e. Cross-encoder re-ranking
        try:
            sources = await self.reranker.rerank(question, sources)
            logger.info("[%s] After re-ranking: %d source documents", rid, len(sources))
        except Exception as exc:
            logger.warning("[%s] Re-ranking failed, using original order: %s", rid, exc)

        # 2f. Confidence-gated multi-hop retrieval
        # If top reranked score is weak, extract novel terms from retrieved
        # chunks and do a BM25-only second pass to find related pages.
        top_score = sources[0].score if sources else 0.0
        if top_score < 0.60 and sources:
            hop2_sources = await self._multi_hop_retrieve(
                question, sources, effective_keys, rid
            )
            if hop2_sources:
                # Merge and re-rank the combined set
                existing_ids = {(s.page_id, s.excerpt[:100]) for s in sources}
                new_hop = [s for s in hop2_sources if (s.page_id, s.excerpt[:100]) not in existing_ids]
                if new_hop:
                    sources.extend(new_hop)
                    logger.info("[%s] Multi-hop added %d sources, re-ranking combined set", rid, len(new_hop))
                    try:
                        sources = await self.reranker.rerank(question, sources)
                    except Exception as exc:
                        logger.warning("[%s] Multi-hop re-rank failed: %s", rid, exc)

        return sources

    async def _multi_hop_retrieve(
        self,
        question: str,
        hop1_sources: list[SourceDocument],
        space_keys: list[str] | None,
        rid: str,
    ) -> list[SourceDocument]:
        """Extract novel terms from Hop 1 chunks and do a BM25-only second search.

        This finds related pages that share terminology with the first-hop results
        but weren't surfaced by the original query. Runs only when first-hop
        confidence is low (gated by caller).
        """
        # Tokenize the question to know which terms we already searched for
        question_tokens = set(bm25_tokenize(question))

        # Extract tokens from the top 3 hop-1 source titles + first 200 chars of content
        chunk_tokens: set[str] = set()
        for src in hop1_sources[:3]:
            title_text = src.title or ""
            excerpt_text = (src.content or src.excerpt or "")[:200]
            chunk_tokens.update(bm25_tokenize(f"{title_text} {excerpt_text}"))

        # Novel terms = in chunks but NOT in question (these are new leads)
        novel_terms = chunk_tokens - question_tokens
        if not novel_terms:
            return []

        # Pick the most distinctive terms (not too common — skip very short ones)
        # Combine with original question terms for a richer query
        novel_sorted = sorted(novel_terms, key=len, reverse=True)[:8]
        hop2_query = " ".join(list(question_tokens)[:5] + novel_sorted)

        logger.info("[%s] Multi-hop query (novel terms): %s", rid, hop2_query[:120])

        # BM25-only search (no embedding needed — fast)
        hop2_sources = await self.vector_store.search(
            query_vector=[],  # empty — triggers BM25-only path
            top_k=self._settings.retrieval_top_k,
            score_threshold=0.0,
            space_keys=space_keys,
            query_text=hop2_query,
        )
        logger.info("[%s] Multi-hop retrieved %d sources", rid, len(hop2_sources))
        return hop2_sources

    def _build_llm_context(
        self,
        sources: list[SourceDocument],
        rid: str,
    ) -> list[dict]:
        """Step 3: Build context dicts for the LLM prompt, apply content guardrail."""
        max_words = self._settings.max_context_words_per_source
        llm_sources = sources[: self._settings.llm_max_sources]
        context_chunks = [
            {
                "title": src.title,
                "text": " ".join((src.content or src.excerpt).split()[:max_words]),
            }
            for src in llm_sources
        ]
        logger.info(
            "[%s] Built context from %d/%d chunks (%d max words each)",
            rid, len(context_chunks), len(sources), max_words,
        )

        context_chunks, redaction_count = self.content_guardrail.redact_chunks(context_chunks)
        if redaction_count:
            logger.info("[%s] Content guardrail redacted %d sensitive pattern(s)", rid, redaction_count)

        return context_chunks

    async def stream(
        self,
        question: str,
        space_keys: list[str] | None = None,
        history: list[dict] | None = None,
        request_id: str | None = None,
        conversation_store=None,
        entity_store: EntityStore | None = None,
        force_fresh: bool = False,
        skip_rewrite: bool = False,
        original_question: str | None = None,
    ) -> AsyncIterator[tuple[str, list[SourceDocument] | None]]:
        """
        Async generator yielding ``(token, None)`` during streaming,
        followed by one final ``("", sources)`` tuple.

        Args:
            question:   The user's natural language question.
            space_keys: Optional Qdrant space filter.
            history:    Previous turns as ``[{"role": "user"|"assistant", "content": "..."}]``.
            request_id: Correlation ID added to every log line.

        Usage::
            async for token, sources in pipeline.stream(question):
                if sources is not None:
                    # final event — attach citations to UI
                    ...
                else:
                    # stream token to client
                    ...
        """
        rid = request_id or "-"

        # 1. Embed question + start query rewrite in parallel
        logger.info("[%s] Embedding question: %r", rid, question[:80])

        async def _embed_original():
            return await self.embeddings.embed(question)

        async def _maybe_rewrite():
            return await rewrite_query(question, self._settings)

        embed_task = asyncio.create_task(_embed_original())
        rewrite_task = asyncio.create_task(_maybe_rewrite()) if (not skip_rewrite and needs_rewrite(question)) else None

        query_vector = await embed_task

        # 1b. Check semantic cache
        if force_fresh:
            logger.info("[%s] force_fresh=True — skipping semantic cache", rid)
            cached = None
        else:
            cached = await self.semantic_cache.lookup(query_vector, question=question)
        if cached is not None:
            if rewrite_task:
                rewrite_task.cancel()
            cached_answer, cached_sources = cached
            logger.info("[%s] Semantic cache hit — returning cached answer", rid)
            yield cached_answer, None
            yield "", cached_sources
            return

        # 2. Retrieve relevant chunks
        sources = await self._retrieve(
            question, query_vector, space_keys, rewrite_task,
            entity_store, conversation_store, rid,
        )

        # 2f. Dual-query fallback: if spell correction changed the query and
        # the corrected query found few/no results, also search with the
        # original query and merge.  This prevents corrections from hiding
        # valid results (e.g. searching for a product name the corpus
        # doesn't know yet).
        if original_question and len(sources) < self._settings.retrieval_top_k:
            logger.info("[%s] Dual-query: also searching with original %r", rid, original_question[:80])
            orig_vector = await self.embeddings.embed(original_question)
            orig_sources = await self.vector_store.search(
                query_vector=orig_vector,
                top_k=self._settings.retrieval_top_k,
                score_threshold=self._settings.retrieval_score_threshold,
                space_keys=space_keys,
                query_text=original_question,
            )
            if orig_sources:
                existing_ids = {(s.page_id, s.excerpt[:100]) for s in sources}
                new = [s for s in orig_sources if (s.page_id, s.excerpt[:100]) not in existing_ids]
                if new:
                    sources.extend(new)
                    logger.info("[%s] Dual-query added %d sources from original query (total: %d)", rid, len(new), len(sources))

        if not sources:
            yield _NO_CONTEXT_REPLY, None
            yield "", []
            return

        # 3. Build context for LLM
        context_chunks = self._build_llm_context(sources, rid)

        # 4. Stream LLM answer
        full_answer_parts: list[str] = []
        async for token in self.llm.stream_answer(question, context_chunks, history=history):
            token = self.content_guardrail.redact_output(token)
            full_answer_parts.append(token)
            yield token, None

        # 5. Store in semantic cache (skip negative answers)
        full_answer = "".join(full_answer_parts)
        _negative_phrases = (
            "i don't have enough information",
            "i could not find",
            "i couldn't find",
            "no relevant information",
            "not enough information",
            "i cannot answer",
            "i can't answer",
            "unable to find",
            "no information available",
        )
        answer_lower = full_answer.lower()
        is_negative = any(phrase in answer_lower for phrase in _negative_phrases)
        if is_negative:
            logger.info("[%s] Skipping cache — LLM produced a negative/no-answer response", rid)
        else:
            await self.semantic_cache.store(question, query_vector, full_answer, sources)

        # 6. Emit sources as final event
        yield "", sources
