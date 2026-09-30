"""
Lightweight entity extraction and storage (Cognee-lite).

Extracts key entities from document text using the LLM during ingestion
and stores them in SQLite. At query time, question entities are matched
against stored entities to boost relevant pages in retrieval.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

import aiosqlite
import httpx

from app.config import Settings

logger = logging.getLogger(__name__)

_ENTITY_SCHEMA = """
CREATE TABLE IF NOT EXISTS page_entities (
    page_id  TEXT NOT NULL,
    entity   TEXT NOT NULL,
    relation TEXT NOT NULL DEFAULT 'MENTIONS',
    target   TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (page_id, entity, relation, target)
);
CREATE INDEX IF NOT EXISTS idx_entity ON page_entities(entity COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_target ON page_entities(target COLLATE NOCASE);
"""

_EXTRACT_PROMPT = """\
Extract the key named entities from the following text. \
Return ONLY a JSON array of strings — entity names only (people, technologies, \
tools, products, processes, teams, acronyms, policies). \
Maximum 15 entities. No duplicates. No explanations.

Text:
{text}

JSON array:"""


class EntityStore:
    """SQLite-backed entity store for Cognee-lite entity extraction."""

    def __init__(self, settings: Settings, db_path: str) -> None:
        self._settings = settings
        self._db_path = db_path
        self._ollama_url = f"{settings.ollama_base_url.rstrip('/')}/api/generate"
        self._model = settings.ollama_llm_model

    @classmethod
    async def create(cls, settings: Settings, db_path: str) -> "EntityStore":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        instance = cls(settings, db_path)
        async with aiosqlite.connect(db_path) as db:
            await db.executescript(_ENTITY_SCHEMA)
            await db.commit()
        logger.info("EntityStore ready at %s", db_path)
        return instance

    async def extract_and_store(self, page_id: str, text: str) -> list[str]:
        """Extract entities from text via LLM and store in SQLite.

        Returns the list of extracted entity strings.
        """
        entities = await self._extract_entities(text[:3000])  # cap input length
        if not entities:
            return []

        async with aiosqlite.connect(self._db_path) as db:
            # Clear old entities for this page (re-ingestion)
            await db.execute("DELETE FROM page_entities WHERE page_id = ?", (page_id,))
            for entity in entities:
                await db.execute(
                    "INSERT OR IGNORE INTO page_entities (page_id, entity) VALUES (?, ?)",
                    (page_id, entity.lower().strip()),
                )
            await db.commit()

        logger.debug("Extracted %d entities for page %s", len(entities), page_id)
        return entities

    async def find_pages_by_entities(self, question: str) -> list[str]:
        """Extract entities from a question and find pages mentioning them.

        Returns a list of page_ids ranked by entity match count (descending).
        """
        entities = self._extract_keywords(question)
        if not entities:
            return []

        placeholders = ",".join("?" for _ in entities)
        query = f"""
            SELECT page_id, COUNT(DISTINCT entity) as matches
            FROM page_entities
            WHERE entity IN ({placeholders})
            GROUP BY page_id
            ORDER BY matches DESC
            LIMIT 20
        """
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(query, [e.lower().strip() for e in entities]) as cur:
                rows = await cur.fetchall()

        return [row[0] for row in rows]

    async def _extract_entities(self, text: str) -> list[str]:
        """Call Ollama to extract entities from text."""
        prompt = _EXTRACT_PROMPT.format(text=text[:3000])
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(connect=5, read=30, write=5, pool=5)
            ) as client:
                resp = await client.post(
                    self._ollama_url,
                    json={
                        "model": self._model,
                        "prompt": prompt,
                        "stream": False,
                        "options": {"temperature": 0.0, "num_predict": 256},
                    },
                )
                data = resp.json()
                raw = data.get("response", "")
                return self._parse_json_array(raw)
        except Exception as exc:
            logger.warning("Entity extraction failed: %s", exc)
            return []

    @staticmethod
    def _parse_json_array(raw: str) -> list[str]:
        """Robustly parse a JSON array from LLM output."""
        # Find the JSON array in the response
        match = re.search(r"\[.*?\]", raw, re.DOTALL)
        if not match:
            return []
        try:
            arr = json.loads(match.group())
            return [str(item).strip() for item in arr if isinstance(item, str) and item.strip()][:15]
        except (json.JSONDecodeError, TypeError):
            return []

    @staticmethod
    def _extract_keywords(text: str) -> list[str]:
        """Fast keyword extraction from a question (no LLM call).

        Extracts meaningful words (4+ chars, not common stop words) from the
        question text for entity matching at query time.
        """
        _STOP_WORDS = {
            "what", "where", "when", "which", "about", "does", "have", "been",
            "this", "that", "these", "those", "with", "from", "they", "them",
            "their", "there", "here", "will", "would", "could", "should",
            "into", "also", "just", "more", "most", "some", "than", "then",
            "very", "only", "each", "much", "many", "such", "well", "like",
            "your", "need", "help", "tell", "know",
        }
        words = re.findall(r"\b[a-zA-Z][\w-]{2,}\b", text)
        return [
            w for w in words
            if len(w) >= 4 and w.lower() not in _STOP_WORDS
        ]
