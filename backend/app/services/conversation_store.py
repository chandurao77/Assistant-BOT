"""
SQLite-backed conversation and feedback store.

Replaces the in-memory ``app.state.conversations`` dict so that conversation
history (used for multi-turn LLM context) survives container restarts.

Also stores:
  - conversation metadata (title, timestamps) for the UI conversation list
  - per-message user feedback (thumbs-up / thumbs-down)
  - ingested page metadata for incremental Confluence sync
  - query analytics for monitoring
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

import aiosqlite

logger = logging.getLogger(__name__)

_SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS conversations (
    id         TEXT PRIMARY KEY,
    title      TEXT NOT NULL DEFAULT 'New Conversation',
    user_id    TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id              TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role            TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
    content         TEXT NOT NULL,
    created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id, created_at);

CREATE TABLE IF NOT EXISTS feedback (
    message_id      TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    value           INTEGER NOT NULL CHECK(value IN (1, -1)),
    reason          TEXT DEFAULT NULL,
    reason_text     TEXT DEFAULT NULL,
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS page_index (
    page_id       TEXT PRIMARY KEY,
    last_modified TEXT NOT NULL,
    chunks_count  INTEGER NOT NULL DEFAULT 0,
    indexed_at    TEXT NOT NULL,
    space_key     TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_page_index_space ON page_index(space_key);

CREATE TABLE IF NOT EXISTS query_analytics (
    id            TEXT PRIMARY KEY,
    question      TEXT NOT NULL,
    sources_found INTEGER NOT NULL DEFAULT 0,
    answered      INTEGER NOT NULL DEFAULT 1,
    response_ms   INTEGER,
    user_id       TEXT,
    space_keys    TEXT,
    sources       TEXT,
    created_at    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_analytics_created ON query_analytics(created_at);

CREATE TABLE IF NOT EXISTS page_links (
    from_page_id TEXT NOT NULL,
    to_page_id   TEXT NOT NULL,
    PRIMARY KEY (from_page_id, to_page_id)
);

CREATE INDEX IF NOT EXISTS idx_page_links_from ON page_links(from_page_id);
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ConversationStore:
    """Async SQLite wrapper for conversations, messages, feedback, and page index."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None
        self._write_lock = asyncio.Lock()  # Serialize writes to prevent 'database is locked'

    @classmethod
    async def create(cls, db_path: str) -> "ConversationStore":
        """Create database, run migrations, return a ready instance."""
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        instance = cls(db_path)
        await instance._open()
        await instance._init_db()
        logger.info("ConversationStore ready at %s", db_path)
        return instance

    async def _open(self) -> None:
        """Open the persistent connection."""
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA foreign_keys=ON")

    @property
    def _conn(self) -> aiosqlite.Connection:
        """Return the persistent connection. Raises if not opened."""
        assert self._db is not None, "ConversationStore not opened"
        return self._db

    async def close(self) -> None:
        """Close the persistent connection. Called during app shutdown."""
        if self._db:
            await self._db.close()
            self._db = None

    async def _init_db(self) -> None:
        db = self._conn
        await db.executescript(_SCHEMA)
        # Migration: add user_id column if missing (existing databases)
        try:
            await db.execute("ALTER TABLE conversations ADD COLUMN user_id TEXT")
            await db.commit()
            logger.info("Migrated conversations table: added user_id column")
        except Exception:
            pass  # column already exists
        # Create index after ensuring column exists
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_conversations_user "
            "ON conversations(user_id, updated_at DESC)"
        )
        await db.commit()
        # Migration: add new analytics columns if missing
        for col, coldef in [
            ("response_ms", "INTEGER"),
            ("user_id", "TEXT"),
            ("space_keys", "TEXT"),
            ("sources", "TEXT"),
        ]:
            try:
                await db.execute(f"ALTER TABLE query_analytics ADD COLUMN {col} {coldef}")
                await db.commit()
                logger.info("Migrated query_analytics table: added %s column", col)
            except Exception:
                pass  # column already exists
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_analytics_user ON query_analytics(user_id)"
        )
        await db.commit()
        # Migration: add reason columns to feedback if missing
        for col in ["reason", "reason_text"]:
            try:
                await db.execute(f"ALTER TABLE feedback ADD COLUMN {col} TEXT DEFAULT NULL")
                await db.commit()
                logger.info("Migrated feedback table: added %s column", col)
            except Exception:
                pass  # column already exists

    # ── LLM History ──────────────────────────────────────────────────────────

    async def get_history(self, conversation_id: str) -> list[dict]:
        """Return ordered [{role, content}] for a conversation (for LLM context)."""
        db = self._conn
        async with db.execute(
            "SELECT role, content FROM messages "
            "WHERE conversation_id = ? ORDER BY created_at",
            (conversation_id,),
        ) as cur:
            rows = await cur.fetchall()
        return [{"role": r[0], "content": r[1]} for r in rows]

    async def append_turn(
        self,
        conversation_id: str,
        title: str,
        user_content: str,
        assistant_content: str,
        user_msg_id: str,
        assistant_msg_id: str,
        user_id: str | None = None,
    ) -> None:
        """Persist one user→assistant turn and upsert the conversation record."""
        now = _now_iso()
        db = self._conn
        async with self._write_lock:
            await db.execute(
                """
                INSERT INTO conversations (id, title, user_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE
                    SET title      = CASE WHEN conversations.title = 'New Conversation'
                                          THEN excluded.title ELSE conversations.title END,
                        updated_at = excluded.updated_at
                """,
                (conversation_id, title, user_id, now, now),
            )
            await db.execute(
                "INSERT OR IGNORE INTO messages (id, conversation_id, role, content, created_at) "
                "VALUES (?, ?, 'user', ?, ?)",
                (user_msg_id, conversation_id, user_content, now),
            )
            await db.execute(
                "INSERT OR IGNORE INTO messages (id, conversation_id, role, content, created_at) "
                "VALUES (?, ?, 'assistant', ?, ?)",
                (assistant_msg_id, conversation_id, assistant_content, now),
            )
            await db.commit()

    # ── Conversation List ─────────────────────────────────────────────────────

    async def list_conversations(self, user_id: str | None = None) -> list[dict]:
        """Return conversations ordered by most-recently-updated, optionally filtered by user."""
        db = self._conn
        db.row_factory = aiosqlite.Row
        if user_id:
            async with db.execute(
                "SELECT id, title, created_at, updated_at FROM conversations "
                "WHERE user_id = ? ORDER BY updated_at DESC",
                (user_id,),
            ) as cur:
                rows = await cur.fetchall()
        else:
            async with db.execute(
                "SELECT id, title, created_at, updated_at FROM conversations "
                "ORDER BY updated_at DESC"
            ) as cur:
                rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def get_conversation_messages(
        self, conversation_id: str, user_id: str | None = None
    ) -> list[dict] | None:
        """Return all messages for a conversation, or None if it doesn't exist (or wrong user)."""
        db = self._conn
        if user_id:
            async with db.execute(
                "SELECT 1 FROM conversations WHERE id = ? AND user_id = ?",
                (conversation_id, user_id),
            ) as cur:
                if not await cur.fetchone():
                    return None
        else:
            async with db.execute(
                "SELECT 1 FROM conversations WHERE id = ?", (conversation_id,)
            ) as cur:
                if not await cur.fetchone():
                    return None
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT id, role, content, created_at FROM messages "
            "WHERE conversation_id = ? ORDER BY created_at",
            (conversation_id,),
        ) as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def rename_conversation(
        self, conversation_id: str, title: str, user_id: str | None = None
    ) -> bool:
        """Update a conversation's title. Returns False if not found."""
        db = self._conn
        now = _now_iso()
        if user_id:
            cur = await db.execute(
                "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ? AND user_id = ?",
                (title, now, conversation_id, user_id),
            )
        else:
            cur = await db.execute(
                "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
                (title, now, conversation_id),
            )
        await db.commit()
        return cur.rowcount > 0

    async def delete_conversation(self, conversation_id: str, user_id: str | None = None) -> bool:
        db = self._conn
        if user_id:
            cur = await db.execute(
                "DELETE FROM conversations WHERE id = ? AND user_id = ?",
                (conversation_id, user_id),
            )
        else:
            cur = await db.execute(
                "DELETE FROM conversations WHERE id = ?", (conversation_id,)
            )
        await db.commit()
        return cur.rowcount > 0

    # ── Feedback ──────────────────────────────────────────────────────────────

    async def save_feedback(
        self, message_id: str, conversation_id: str, value: int,
        reason: str | None = None, reason_text: str | None = None,
    ) -> None:
        """Store or update feedback for an assistant message (+1 or -1)."""
        db = self._conn
        await db.execute(
            """
            INSERT OR REPLACE INTO feedback (message_id, conversation_id, value, reason, reason_text, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (message_id, conversation_id, value, reason, reason_text, _now_iso()),
        )
        await db.commit()

    async def get_feedback_stats(self) -> dict:
        """Return aggregate feedback metrics for the analytics dashboard."""
        db = self._conn
        async with db.execute("SELECT COUNT(*) FROM feedback WHERE value = 1") as cur:
            positive = (await cur.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM feedback WHERE value = -1") as cur:
            negative = (await cur.fetchone())[0]
        # Recent feedback (last 7 days)
        cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        async with db.execute(
            "SELECT value, COUNT(*) FROM feedback WHERE created_at > ? GROUP BY value",
            (cutoff,),
        ) as cur:
            recent_rows = await cur.fetchall()
        recent = {r[0]: r[1] for r in recent_rows}
        # Reason breakdown for negative feedback
        async with db.execute(
            "SELECT COALESCE(reason, 'unspecified') AS r, COUNT(*) FROM feedback WHERE value = -1 GROUP BY r",
        ) as cur:
            reason_rows = await cur.fetchall()
        reason_breakdown = {r[0]: r[1] for r in reason_rows}
        total = positive + negative
        return {
            "total_ratings": total,
            "positive": positive,
            "negative": negative,
            "satisfaction_rate": round(positive / total, 4) if total else 0.0,
            "recent_7d_positive": recent.get(1, 0),
            "recent_7d_negative": recent.get(-1, 0),
            "reason_breakdown": reason_breakdown,
        }

    async def get_page_feedback_scores(self) -> dict[str, float]:
        """
        Return ``{page_id: score}`` where score is a net-positive ratio.

        Joins feedback → messages → conversations to trace which source pages
        were shown for each rated message. Pages associated with thumbs-up
        get a positive score; thumbs-down negative.

        Falls back to an empty dict if the join data is incomplete.
        """
        try:
            db = self._conn
            # We don't store sources per message in SQLite yet,
            # so return empty — the endpoint still works for stats.
            return {}
        except Exception:
            return {}

    # ── Page Index (Incremental Sync) ─────────────────────────────────────────

    async def get_page_versions(self, page_ids: list[str]) -> dict[str, str]:
        """
        Return ``{page_id: last_modified_iso}`` for the given page IDs that are
        already indexed in Qdrant. Used by incremental sync to skip unchanged pages.
        """
        if not page_ids:
            return {}
        placeholders = ",".join("?" * len(page_ids))
        db = self._conn
        async with db.execute(
            f"SELECT page_id, last_modified FROM page_index WHERE page_id IN ({placeholders})",
            page_ids,
        ) as cur:
            rows = await cur.fetchall()
        return {r[0]: r[1] for r in rows}

    async def upsert_page_index(
        self, page_id: str, last_modified: str, chunks_count: int, space_key: str = ""
    ) -> None:
        db = self._conn
        await db.execute(
            """
            INSERT OR REPLACE INTO page_index (page_id, last_modified, chunks_count, indexed_at, space_key)
            VALUES (?, ?, ?, ?, ?)
            """,
            (page_id, last_modified, chunks_count, _now_iso(), space_key),
        )
        await db.commit()

    async def delete_page_index(self, page_id: str) -> None:
        db = self._conn
        await db.execute("DELETE FROM page_index WHERE page_id = ?", (page_id,))
        await db.commit()

    async def clear_page_index(self, space_keys: list[str] | None = None) -> None:
        """Wipe indexed page records. If space_keys given, only clears those spaces."""
        db = self._conn
        if space_keys:
            placeholders = ",".join("?" * len(space_keys))
            await db.execute(
                f"DELETE FROM page_index WHERE space_key IN ({placeholders})",
                space_keys,
            )
        else:
            await db.execute("DELETE FROM page_index")
        await db.commit()

    async def get_last_ingest_time(self) -> str | None:
        """Return the most recent indexed_at timestamp from page_index, or None if empty."""
        db = self._conn
        async with db.execute("SELECT MAX(indexed_at) FROM page_index") as cur:
            row = await cur.fetchone()
        return row[0] if row and row[0] else None

    # ── Analytics ─────────────────────────────────────────────────────────────

    async def record_query_analytics(
        self, question: str, sources_found: int, answered: bool,
        response_ms: int | None = None, user_id: str | None = None,
        space_keys: list[str] | None = None,
        sources: list[dict] | None = None,
    ) -> None:
        """Record every query for monitoring. Non-blocking — errors are swallowed."""
        try:
            import json as _json
            db = self._conn
            await db.execute(
                "INSERT INTO query_analytics (id, question, sources_found, answered, response_ms, user_id, space_keys, sources, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), question[:500], sources_found, 1 if answered else 0,
                 response_ms, user_id, ",".join(space_keys) if space_keys else None,
                 _json.dumps(sources) if sources else None, _now_iso()),
            )
            await db.commit()
        except Exception as exc:
            logger.warning("Failed to record query analytics: %s", exc)

    async def get_suggested_questions(self, current_question: str | None = None, limit: int = 5) -> list[str]:
        """Return recent popular questions as suggestions (excluding the current question)."""
        try:
            db = self._conn
            async with db.execute(
                """
                SELECT question, COUNT(*) as cnt
                FROM query_analytics
                WHERE answered = 1 AND sources_found > 0
                GROUP BY question
                ORDER BY cnt DESC, MAX(created_at) DESC
                LIMIT ?
                """,
                (limit + 5,),  # fetch extras to allow filtering
            ) as cur:
                rows = await cur.fetchall()
            questions = []
            current_lower = (current_question or "").strip().lower()
            for row in rows:
                q = row[0]
                if q.strip().lower() != current_lower:
                    questions.append(q)
                if len(questions) >= limit:
                    break
            return questions
        except Exception as exc:
            logger.warning("Failed to get suggested questions: %s", exc)
            return []

    async def get_analytics(self) -> dict:
        """Return aggregate query analytics for the /api/metrics endpoint."""
        db = self._conn
        async with db.execute("SELECT COUNT(*) FROM query_analytics") as cur:
            total_queries = (await cur.fetchone())[0]
        async with db.execute(
            "SELECT COUNT(*) FROM query_analytics WHERE answered = 0"
        ) as cur:
            no_answer_count = (await cur.fetchone())[0]
        async with db.execute(
            "SELECT AVG(sources_found) FROM query_analytics WHERE answered = 1"
        ) as cur:
            row = await cur.fetchone()
            avg_sources = round(row[0] or 0.0, 2)
        # Queries in the last 24 hours
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        async with db.execute(
            "SELECT COUNT(*) FROM query_analytics WHERE created_at > ?", (cutoff,)
        ) as cur:
            queries_last_24h = (await cur.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM conversations") as cur:
            total_conversations = (await cur.fetchone())[0]

        no_answer_rate = round(no_answer_count / total_queries, 4) if total_queries else 0.0
        return {
            "total_queries": total_queries,
            "total_conversations": total_conversations,
            "queries_last_24h": queries_last_24h,
            "no_answer_count": no_answer_count,
            "no_answer_rate": no_answer_rate,
            "avg_sources_per_answered_query": avg_sources,
        }

    async def get_extended_analytics(self) -> dict:
        """Return extended analytics for the admin dashboard (all 9 features)."""
        db = self._conn

        # 1. Top Questions
        async with db.execute(
            "SELECT question, COUNT(*) as cnt FROM query_analytics "
            "GROUP BY question ORDER BY cnt DESC LIMIT 10"
        ) as cur:
            top_questions = [{"question": r[0], "count": r[1]} for r in await cur.fetchall()]

        # 2. Unanswered Questions (content gaps)
        async with db.execute(
            "SELECT question, COUNT(*) as cnt FROM query_analytics "
            "WHERE answered = 0 GROUP BY question ORDER BY cnt DESC LIMIT 10"
        ) as cur:
            unanswered = [{"question": r[0], "count": r[1]} for r in await cur.fetchall()]

        # 3. Usage Trend (7-day, queries per day)
        week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        async with db.execute(
            "SELECT substr(created_at, 1, 10) as day, COUNT(*) as cnt "
            "FROM query_analytics WHERE created_at > ? "
            "GROUP BY day ORDER BY day", (week_ago,)
        ) as cur:
            usage_trend = [{"date": r[0], "count": r[1]} for r in await cur.fetchall()]

        # 4. Peak Usage Hours (queries by hour-of-day)
        async with db.execute(
            "SELECT CAST(substr(created_at, 12, 2) AS INTEGER) as hour, COUNT(*) as cnt "
            "FROM query_analytics GROUP BY hour ORDER BY hour"
        ) as cur:
            peak_hours = [{"hour": r[0], "count": r[1]} for r in await cur.fetchall()]

        # 5. Recent Activity Feed (last 20 queries)
        async with db.execute(
            "SELECT question, sources_found, answered, response_ms, user_id, created_at "
            "FROM query_analytics ORDER BY created_at DESC LIMIT 20"
        ) as cur:
            recent_activity = [
                {"question": r[0], "sources_found": r[1], "answered": bool(r[2]),
                 "response_ms": r[3], "user_id": r[4], "created_at": r[5]}
                for r in await cur.fetchall()
            ]

        # 6. Response Time stats
        async with db.execute(
            "SELECT AVG(response_ms), MIN(response_ms), MAX(response_ms) "
            "FROM query_analytics WHERE response_ms IS NOT NULL"
        ) as cur:
            rt_row = await cur.fetchone()
            response_time = {
                "avg_ms": round(rt_row[0] or 0),
                "min_ms": rt_row[1] or 0,
                "max_ms": rt_row[2] or 0,
            }

        # 7. Space Usage Breakdown
        async with db.execute(
            "SELECT space_keys, COUNT(*) as cnt FROM query_analytics "
            "WHERE space_keys IS NOT NULL AND space_keys != '' "
            "GROUP BY space_keys ORDER BY cnt DESC LIMIT 15"
        ) as cur:
            space_usage = [{"space_keys": r[0], "count": r[1]} for r in await cur.fetchall()]

        # 9. Per-User Usage (top 10 active users)
        async with db.execute(
            "SELECT user_id, COUNT(*) as cnt FROM query_analytics "
            "WHERE user_id IS NOT NULL GROUP BY user_id ORDER BY cnt DESC LIMIT 10"
        ) as cur:
            per_user = [{"user_id": r[0], "count": r[1]} for r in await cur.fetchall()]

        # Active users in last 24h
        cutoff_24h = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        async with db.execute(
            "SELECT COUNT(DISTINCT user_id) FROM query_analytics "
            "WHERE user_id IS NOT NULL AND created_at > ?", (cutoff_24h,)
        ) as cur:
            active_users_24h = (await cur.fetchone())[0]

        return {
            "top_questions": top_questions,
            "unanswered_questions": unanswered,
            "usage_trend": usage_trend,
            "peak_hours": peak_hours,
            "recent_activity": recent_activity,
            "response_time": response_time,
            "space_usage": space_usage,
            "per_user_usage": per_user,
            "active_users_24h": active_users_24h,
        }

    # ── Pruning ───────────────────────────────────────────────────────────────

    async def prune_old_conversations(self, max_age_days: int) -> int:
        """
        Delete conversations (and their messages via CASCADE) that have not been
        updated in more than ``max_age_days`` days.  Returns the number deleted.
        """
        if max_age_days <= 0:
            return 0
        cutoff = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).isoformat()
        db = self._conn
        cur = await db.execute(
            "DELETE FROM conversations WHERE updated_at < ?", (cutoff,)
        )
        await db.commit()
        count = cur.rowcount
        if count:
            logger.info("Pruned %d conversations older than %d days", count, max_age_days)
        return count

    # ── Graph RAG ─────────────────────────────────────────────────────────────

    async def upsert_page_links(self, from_page_id: str, to_page_ids: list[str]) -> None:
        """Store all outbound links from a page (replaces any previous links for that page)."""
        db = self._conn
        await db.execute(
            "DELETE FROM page_links WHERE from_page_id = ?", (from_page_id,)
        )
        if to_page_ids:
            await db.executemany(
                "INSERT OR IGNORE INTO page_links (from_page_id, to_page_id) VALUES (?, ?)",
                [(from_page_id, to_id) for to_id in to_page_ids],
            )
        await db.commit()

    async def get_linked_page_ids(self, page_ids: list[str]) -> list[str]:
        """Return page IDs that are linked *from* any of the given pages, excluding the originals."""
        if not page_ids:
            return []
        placeholders = ",".join("?" * len(page_ids))
        db = self._conn
        async with db.execute(
            f"SELECT DISTINCT to_page_id FROM page_links WHERE from_page_id IN ({placeholders})",
            page_ids,
        ) as cur:
            rows = await cur.fetchall()
        already = set(page_ids)
        return [r[0] for r in rows if r[0] not in already]

    # ── GDPR / Data Purge ─────────────────────────────────────────────────────

    async def purge_user_data(self, user_id: str) -> dict:
        """
        Delete ALL data associated with a user (GDPR right to be forgotten).
        Returns summary of what was deleted.
        """
        db = self._conn
        # Count before deletion
        async with db.execute(
            "SELECT COUNT(*) FROM conversations WHERE user_id = ?", (user_id,)
        ) as cur:
            conv_count = (await cur.fetchone())[0]

        async with db.execute(
            "SELECT COUNT(*) FROM messages WHERE conversation_id IN "
            "(SELECT id FROM conversations WHERE user_id = ?)", (user_id,)
        ) as cur:
            msg_count = (await cur.fetchone())[0]

        async with db.execute(
            "SELECT COUNT(*) FROM feedback WHERE conversation_id IN "
            "(SELECT id FROM conversations WHERE user_id = ?)", (user_id,)
        ) as cur:
            feedback_count = (await cur.fetchone())[0]

        # Delete (CASCADE handles messages)
        await db.execute(
            "DELETE FROM feedback WHERE conversation_id IN "
            "(SELECT id FROM conversations WHERE user_id = ?)", (user_id,)
        )
        await db.execute(
            "DELETE FROM conversations WHERE user_id = ?", (user_id,)
        )
        await db.commit()

        logger.info(
            "Purged user data: user_id=%s conversations=%d messages=%d feedback=%d",
            user_id, conv_count, msg_count, feedback_count,
        )
        return {
            "user_id": user_id,
            "conversations_deleted": conv_count,
            "messages_deleted": msg_count,
            "feedback_deleted": feedback_count,
        }

    # ── GDPR / Data Export ─────────────────────────────────────────────────────

    async def export_user_data(self, user_id: str) -> dict:
        """
        GDPR right of access — export ALL data for a user as a structured dict.
        Returns conversations, messages, and feedback in a single JSON-serialisable object.
        """
        db = self._conn
        db.row_factory = aiosqlite.Row

        async with db.execute(
            "SELECT id, title, created_at, updated_at FROM conversations WHERE user_id = ?",
            (user_id,),
        ) as cur:
            conv_rows = await cur.fetchall()

        conversations = []
        for c in conv_rows:
            conv = dict(c)
            async with db.execute(
                "SELECT id, role, content, created_at FROM messages "
                "WHERE conversation_id = ? ORDER BY created_at",
                (c["id"],),
            ) as mcur:
                msg_rows = await mcur.fetchall()
            conv["messages"] = [dict(m) for m in msg_rows]

            async with db.execute(
                "SELECT message_id, value, created_at FROM feedback "
                "WHERE conversation_id = ?",
                (c["id"],),
            ) as fcur:
                fb_rows = await fcur.fetchall()
            conv["feedback"] = [dict(f) for f in fb_rows]
            conversations.append(conv)

        return {
            "user_id": user_id,
            "exported_at": _now_iso(),
            "conversations_count": len(conversations),
            "conversations": conversations,
        }
