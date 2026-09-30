"""OKF Graph Enricher.

Extends the existing ``ancestor_titles`` GraphRAG with semantic links extracted
from the ``## Related Concepts`` section of OKF Markdown files.

Responsibilities:
1. Extract ``[[ConceptName]]`` links from OKF content.
2. Resolve concept names to actual page IDs using fuzzy title matching against
   the SQLite ``page_index`` table.
3. Write resolved links into the ``page_links`` table (reuses existing
   ``get_linked_page_ids`` query path in ``conversation_store``).
4. Build ``graph_context`` strings for embedding alongside chunk content.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Regex to extract [[ConceptName]] links
_CONCEPT_LINK_RE = re.compile(r"\[\[(.+?)\]\]")


@dataclass
class EnrichmentResult:
    """Graph enrichment output for one page."""
    page_id: str
    related_concepts: list[str]           # raw concept names from [[...]]
    resolved_page_ids: list[str]          # page IDs matched from page_index
    graph_context: str                    # "Hierarchy: A > B | Related: X, Y"


class EnhancedGraphEnricher:
    """Extend ancestor-title graph RAG with OKF semantic concept links.

    Designed to be called once per page during ingestion, after OKF conversion
    but before embedding.  Writes resolved links to the ``page_links`` SQLite
    table so that ``rag.py._expand_with_links`` picks them up at query time
    without any code changes to the retrieval path.
    """

    def __init__(self, conversation_store) -> None:
        """
        Args:
            conversation_store: The active AsyncConversationStore instance
                (provides ``upsert_page_links`` and access to the DB connection).
        """
        self._store = conversation_store

    # ── Public API ────────────────────────────────────────────────────────────

    def extract_related_concepts(self, okf_content: str) -> list[str]:
        """Parse ``[[ConceptName]]`` links from the Related Concepts section.

        Falls back to searching the full document if the section is missing.

        Args:
            okf_content: Full OKF Markdown text.

        Returns:
            Deduplicated list of concept name strings.
        """
        # Prefer the ## Related Concepts section
        section_match = re.search(
            r"## Related Concepts\s*\n(.*?)(?=\n##|\Z)",
            okf_content,
            re.DOTALL,
        )
        if section_match:
            concepts = _CONCEPT_LINK_RE.findall(section_match.group(1))
        else:
            # Fall back: scan whole document for [[...]] links
            concepts = _CONCEPT_LINK_RE.findall(okf_content)

        # Deduplicate preserving order
        seen: set[str] = set()
        result: list[str] = []
        for c in concepts:
            c = c.strip()
            if c and c not in seen and c.lower() != "none":
                seen.add(c)
                result.append(c)
        return result

    async def resolve_concepts(
        self,
        related_concepts: list[str],
        page_index_rows: list[tuple[str, str]],  # [(page_id, title), ...]
    ) -> list[str]:
        """Match concept names to page IDs using case-insensitive title search.

        Strategy (in order):
        1. Exact match (case-insensitive)
        2. Contains match — concept name appears in title
        3. Reverse contains match — title appears in concept name

        Args:
            related_concepts: Concept names from extract_related_concepts().
            page_index_rows: All (page_id, title) rows from page_index table.

        Returns:
            List of resolved page IDs (deduplicated, max 10).
        """
        # Build lookup structures
        exact: dict[str, str] = {title.lower(): pid for pid, title in page_index_rows}
        all_rows = [(pid, title.lower()) for pid, title in page_index_rows]

        resolved: list[str] = []
        seen: set[str] = set()

        for concept in related_concepts:
            cl = concept.lower().strip()
            pid: str | None = None

            # 1. Exact match
            pid = exact.get(cl)

            # 2. Concept name is contained in a page title
            if not pid:
                for row_pid, row_title in all_rows:
                    if cl in row_title:
                        pid = row_pid
                        break

            # 3. Page title is contained in concept name
            if not pid:
                for row_pid, row_title in all_rows:
                    if len(row_title) >= 5 and row_title in cl:
                        pid = row_pid
                        break

            if pid and pid not in seen:
                seen.add(pid)
                resolved.append(pid)
                if len(resolved) >= 10:
                    break

        return resolved

    async def enrich_page(
        self,
        page_id: str,
        okf_content: str,
        ancestor_titles: list[str],
        page_index_rows: list[tuple[str, str]],
    ) -> EnrichmentResult:
        """Full enrichment for one page: extract → resolve → write page_links.

        Args:
            page_id: Source page ID.
            okf_content: OKF Markdown for this page.
            ancestor_titles: Breadcrumb hierarchy from original Confluence page.
            page_index_rows: Full page_index snapshot for concept resolution.

        Returns:
            EnrichmentResult with concepts, resolved IDs, and graph_context string.
        """
        concepts = self.extract_related_concepts(okf_content)
        resolved_ids = await self.resolve_concepts(concepts, page_index_rows)

        # Write semantic links to page_links table (same table used by existing graph expansion)
        if resolved_ids:
            await self._store.upsert_page_links(page_id, resolved_ids)
            logger.debug(
                "GraphEnricher: page %s → %d semantic links (%d resolved from %d concepts)",
                page_id, len(resolved_ids), len(resolved_ids), len(concepts),
            )

        graph_context = self.build_graph_context(ancestor_titles, concepts)

        return EnrichmentResult(
            page_id=page_id,
            related_concepts=concepts,
            resolved_page_ids=resolved_ids,
            graph_context=graph_context,
        )

    @staticmethod
    def build_graph_context(
        ancestor_titles: list[str],
        related_concepts: list[str],
    ) -> str:
        """Build a compact graph context string for embedding alongside chunk content.

        Format: ``"Hierarchy: A > B > C | Related: X, Y, Z"``
        Either part is omitted if empty.

        Args:
            ancestor_titles: Breadcrumb hierarchy.
            related_concepts: Concept names from OKF.

        Returns:
            Human-readable graph context string (empty string if both are empty).
        """
        parts: list[str] = []
        if ancestor_titles:
            parts.append("Hierarchy: " + " > ".join(ancestor_titles))
        if related_concepts:
            # Limit to 5 most relevant to keep string compact
            parts.append("Related: " + ", ".join(related_concepts[:5]))
        return " | ".join(parts)
