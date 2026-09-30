"""
PostgreSQL-backed conversation and feedback store.

Drop-in replacement for ``ConversationStore`` (SQLite) that uses ``asyncpg``
for native async PostgreSQL access.  Enables horizontal scaling with multiple
backend replicas sharing a single PostgreSQL database.

Supports multi-host failover via comma-separated DATABASE_URL:
    DATABASE_URL=postgresql+asyncpg://assistant_bot:assistant_bot@host1:5432,host2:5432,host3:5432/assistant_bot

When the primary host is unreachable, the store automatically tries the next
host in the list with a 0.5s delay between attempts.

Enable by setting:
    DATABASE_URL=postgresql+asyncpg://assistant_bot:assistant_bot@postgres:5432/assistant_bot

Start PostgreSQL with:
    podman compose --profile postgres up -d
"""
from __future__ import annotations

import asyncio
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone

import asyncpg

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id         TEXT PRIMARY KEY,
    title      TEXT NOT NULL DEFAULT 'New Conversation',
    user_id    TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_conversations_user
    ON conversations(user_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS messages (
    id              TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role            TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
    content         TEXT NOT NULL,
    created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_conv
    ON messages(conversation_id, created_at);

CREATE TABLE IF NOT EXISTS feedback (
    message_id      TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    value           INTEGER NOT NULL CHECK(value IN (1, -1)),
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


# ── Multi-host DSN parsing ────────────────────────────────────────────────────
_MULTI_HOST_RE = re.compile(
    r"^(?P<scheme>postgresql(?:\+asyncpg)?://)(?P<userinfo>[^@]+@)(?P<hosts>[^/]+)(?P<rest>/.*)$"
)


def _parse_dsn(url: str) -> str:
    """Convert SQLAlchemy-style URL to asyncpg-compatible DSN (single host)."""
    return url.replace("postgresql+asyncpg://", "postgresql://")


def _split_hosts(url: str) -> list[str]:
    """Split a multi-host DATABASE_URL into individual single-host DSNs.

    Input:  postgresql+asyncpg://user:pass@host1:5432,host2:5432/dbname
    Output: ["postgresql://user:pass@host1:5432/dbname",
             "postgresql://user:pass@host2:5432/dbname"]
    """
    m = _MULTI_HOST_RE.match(url)
    if not m:
        return [_parse_dsn(url)]
    userinfo = m.group("userinfo")
    hosts = m.group("hosts").split(",")
    rest = m.group("rest")
    return [f"postgresql://{userinfo}{host.strip()}{rest}" for host in hosts]


class PgConversationStore:
    """Async PostgreSQL wrapper — same interface as ``ConversationStore``."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    @classmethod
    async def create(cls, database_url: str) -> "PgConversationStore":
        """Connect to PostgreSQL with multi-host failover, run migrations, return a ready instance.

        Tries each host in order with a 0.5s delay between attempts.
        """
        dsns = _split_hosts(database_url)
        pool = None
        last_error: Exception | None = None

        for i, dsn in enumerate(dsns):
            try:
                pool = await asyncio.wait_for(
                    asyncpg.create_pool(dsn, min_size=2, max_size=10),
                    timeout=10.0,
                )
                if len(dsns) > 1:
                    logger.info("Connected to PostgreSQL host %d/%d", i + 1, len(dsns))
                break
            except Exception as exc:
                last_error = exc
                host_label = dsn.split("@")[-1].split("/")[0] if "@" in dsn else "unknown"
                logger.warning(
                    "PostgreSQL host %d/%d (%s) unreachable: %s — trying next",
                    i + 1, len(dsns), host_label, exc,
                )
                if i < len(dsns) - 1:
                    await asyncio.sleep(0.5)

        if pool is None:
            raise ConnectionError(
                f"All {len(dsns)} PostgreSQL host(s) unreachable. Last error: {last_error}"
            )
        instance = cls(pool)
        await instance._init_db()
        logger.info("PgConversationStore ready (PostgreSQL)")
        return instance

    async def _init_db(self) -> None:
        """Apply schema via inline DDL (safe for dev).

        In production, prefer: ``alembic upgrade head``
        """
        async with self._pool.acquire() as conn:
            await conn.execute(_SCHEMA)
            # Migration: add new analytics columns if missing
            for col, coldef in [
                ("response_ms", "INTEGER"),
                ("user_id", "TEXT"),
                ("space_keys", "TEXT"),
                ("sources", "TEXT"),
            ]:
                try:
                    await conn.execute(f"ALTER TABLE query_analytics ADD COLUMN {col} {coldef}")
                    logger.info("Migrated query_analytics table: added %s column", col)
                except Exception:
                    pass  # column already exists
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_analytics_user ON query_analytics(user_id)"
            )

    async def close(self) -> None:
        await self._pool.close()

    # ── LLM History ──────────────────────────────────────────────────────────

    async def get_history(self, conversation_id: str) -> list[dict]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT role, content FROM messages "
                "WHERE conversation_id = $1 ORDER BY created_at",
                conversation_id,
            )
        return [{"role": r["role"], "content": r["content"]} for r in rows]

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
        now = _now_iso()
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """
                    INSERT INTO conversations (id, title, user_id, created_at, updated_at)
                    VALUES ($1, $2, $3, $4, $5)
                    ON CONFLICT (id) DO UPDATE
                        SET title      = CASE WHEN conversations.title = 'New Conversation'
                                              THEN EXCLUDED.title ELSE conversations.title END,
                            updated_at = EXCLUDED.updated_at
                    """,
                    conversation_id, title, user_id, now, now,
                )
                await conn.execute(
                    "INSERT INTO messages (id, conversation_id, role, content, created_at) "
                    "VALUES ($1, $2, 'user', $3, $4) ON CONFLICT (id) DO NOTHING",
                    user_msg_id, conversation_id, user_content, now,
                )
                await conn.execute(
                    "INSERT INTO messages (id, conversation_id, role, content, created_at) "
                    "VALUES ($1, $2, 'assistant', $3, $4) ON CONFLICT (id) DO NOTHING",
                    assistant_msg_id, conversation_id, assistant_content, now,
                )

    # ── Conversation List ─────────────────────────────────────────────────────

    async def list_conversations(self, user_id: str | None = None) -> list[dict]:
        async with self._pool.acquire() as conn:
            if user_id:
                rows = await conn.fetch(
                    "SELECT id, title, created_at, updated_at FROM conversations "
                    "WHERE user_id = $1 ORDER BY updated_at DESC",
                    user_id,
                )
            else:
                rows = await conn.fetch(
                    "SELECT id, title, created_at, updated_at FROM conversations "
                    "ORDER BY updated_at DESC"
                )
        return [dict(r) for r in rows]

    async def get_conversation_messages(
        self, conversation_id: str, user_id: str | None = None
    ) -> list[dict] | None:
        async with self._pool.acquire() as conn:
            if user_id:
                exists = await conn.fetchval(
                    "SELECT 1 FROM conversations WHERE id = $1 AND user_id = $2",
                    conversation_id, user_id,
                )
            else:
                exists = await conn.fetchval(
                    "SELECT 1 FROM conversations WHERE id = $1", conversation_id
                )
            if not exists:
                return None
            rows = await conn.fetch(
                "SELECT id, role, content, created_at FROM messages "
                "WHERE conversation_id = $1 ORDER BY created_at",
                conversation_id,
            )
        return [dict(r) for r in rows]

    async def rename_conversation(
        self, conversation_id: str, title: str, user_id: str | None = None
    ) -> bool:
        """Update a conversation's title. Returns False if not found."""
        now = _now_iso()
        async with self._pool.acquire() as conn:
            if user_id:
                result = await conn.execute(
                    "UPDATE conversations SET title = $1, updated_at = $2 WHERE id = $3 AND user_id = $4",
                    title, now, conversation_id, user_id,
                )
            else:
                result = await conn.execute(
                    "UPDATE conversations SET title = $1, updated_at = $2 WHERE id = $3",
                    title, now, conversation_id,
                )
        return result != "UPDATE 0"

    async def delete_conversation(self, conversation_id: str, user_id: str | None = None) -> bool:
        async with self._pool.acquire() as conn:
            if user_id:
                result = await conn.execute(
                    "DELETE FROM conversations WHERE id = $1 AND user_id = $2",
                    conversation_id, user_id,
                )
            else:
                result = await conn.execute(
                    "DELETE FROM conversations WHERE id = $1", conversation_id
                )
        return result != "DELETE 0"

    # ── Feedback ──────────────────────────────────────────────────────────────

    async def save_feedback(
        self, message_id: str, conversation_id: str, value: int,
        reason: str | None = None, reason_text: str | None = None,
    ) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO feedback (message_id, conversation_id, value, reason, reason_text, created_at)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (message_id) DO UPDATE
                    SET value = EXCLUDED.value, reason = EXCLUDED.reason,
                        reason_text = EXCLUDED.reason_text, created_at = EXCLUDED.created_at
                """,
                message_id, conversation_id, value, reason, reason_text, _now_iso(),
            )

    async def get_feedback_stats(self) -> dict:
        async with self._pool.acquire() as conn:
            positive = await conn.fetchval("SELECT COUNT(*) FROM feedback WHERE value = 1")
            negative = await conn.fetchval("SELECT COUNT(*) FROM feedback WHERE value = -1")
            cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
            recent_rows = await conn.fetch(
                "SELECT value, COUNT(*) AS cnt FROM feedback WHERE created_at > $1 GROUP BY value",
                cutoff,
            )
            reason_rows = await conn.fetch(
                "SELECT COALESCE(reason, 'unspecified') AS r, COUNT(*) AS cnt FROM feedback WHERE value = -1 GROUP BY r",
            )
        recent = {r["value"]: r["cnt"] for r in recent_rows}
        reason_breakdown = {r["r"]: r["cnt"] for r in reason_rows}
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
        return {}

    # ── Page Index (Incremental Sync) ─────────────────────────────────────────

    async def get_page_versions(self, page_ids: list[str]) -> dict[str, str]:
        if not page_ids:
            return {}
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT page_id, last_modified FROM page_index WHERE page_id = ANY($1::text[])",
                page_ids,
            )
        return {r["page_id"]: r["last_modified"] for r in rows}

    async def upsert_page_index(
        self, page_id: str, last_modified: str, chunks_count: int, space_key: str = ""
    ) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO page_index (page_id, last_modified, chunks_count, indexed_at, space_key)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (page_id) DO UPDATE
                    SET last_modified = EXCLUDED.last_modified,
                        chunks_count  = EXCLUDED.chunks_count,
                        indexed_at    = EXCLUDED.indexed_at,
                        space_key     = EXCLUDED.space_key
                """,
                page_id, last_modified, chunks_count, _now_iso(), space_key,
            )

    async def delete_page_index(self, page_id: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute("DELETE FROM page_index WHERE page_id = $1", page_id)

    async def clear_page_index(self, space_keys: list[str] | None = None) -> None:
        async with self._pool.acquire() as conn:
            if space_keys:
                await conn.execute(
                    "DELETE FROM page_index WHERE space_key = ANY($1::text[])",
                    space_keys,
                )
            else:
                await conn.execute("DELETE FROM page_index")

    async def get_last_ingest_time(self) -> str | None:
        """Return the most recent indexed_at timestamp from page_index, or None if empty."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("SELECT MAX(indexed_at) FROM page_index")
        return row[0] if row and row[0] else None

    # ── Analytics ─────────────────────────────────────────────────────────────

    async def record_query_analytics(
        self, question: str, sources_found: int, answered: bool,
        response_ms: int | None = None, user_id: str | None = None,
        space_keys: list[str] | None = None,
        sources: list[dict] | None = None,
    ) -> None:
        try:
            import json as _json
            async with self._pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO query_analytics (id, question, sources_found, answered, response_ms, user_id, space_keys, sources, created_at) "
                    "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)",
                    str(uuid.uuid4()), question[:500], sources_found,
                    1 if answered else 0, response_ms, user_id,
                    ",".join(space_keys) if space_keys else None,
                    _json.dumps(sources) if sources else None, _now_iso(),
                )
        except Exception as exc:
            logger.warning("Failed to record query analytics: %s", exc)

    async def get_suggested_questions(self, current_question: str | None = None, limit: int = 5) -> list[str]:
        try:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT question, COUNT(*) as cnt
                    FROM query_analytics
                    WHERE answered = 1 AND sources_found > 0
                    GROUP BY question
                    ORDER BY cnt DESC, MAX(created_at) DESC
                    LIMIT $1
                    """,
                    limit + 5,
                )
            questions = []
            current_lower = (current_question or "").strip().lower()
            for row in rows:
                q = row["question"]
                if q.strip().lower() != current_lower:
                    questions.append(q)
                if len(questions) >= limit:
                    break
            return questions
        except Exception as exc:
            logger.warning("Failed to get suggested questions: %s", exc)
            return []

    async def get_analytics(self) -> dict:
        async with self._pool.acquire() as conn:
            total_queries = await conn.fetchval("SELECT COUNT(*) FROM query_analytics")
            no_answer_count = await conn.fetchval(
                "SELECT COUNT(*) FROM query_analytics WHERE answered = 0"
            )
            avg_sources = await conn.fetchval(
                "SELECT AVG(sources_found) FROM query_analytics WHERE answered = 1"
            )
            avg_sources = round(avg_sources or 0.0, 2)
            cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
            queries_last_24h = await conn.fetchval(
                "SELECT COUNT(*) FROM query_analytics WHERE created_at > $1", cutoff
            )
            total_conversations = await conn.fetchval("SELECT COUNT(*) FROM conversations")
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
        async with self._pool.acquire() as conn:
            # 1. Top Questions
            rows = await conn.fetch(
                "SELECT question, COUNT(*) as cnt FROM query_analytics "
                "GROUP BY question ORDER BY cnt DESC LIMIT 10"
            )
            top_questions = [{"question": r["question"], "count": r["cnt"]} for r in rows]

            # 2. Unanswered Questions
            rows = await conn.fetch(
                "SELECT question, COUNT(*) as cnt FROM query_analytics "
                "WHERE answered = 0 GROUP BY question ORDER BY cnt DESC LIMIT 10"
            )
            unanswered = [{"question": r["question"], "count": r["cnt"]} for r in rows]

            # 3. Usage Trend (7-day)
            week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
            rows = await conn.fetch(
                "SELECT substring(created_at from 1 for 10) as day, COUNT(*) as cnt "
                "FROM query_analytics WHERE created_at > $1 "
                "GROUP BY day ORDER BY day", week_ago
            )
            usage_trend = [{"date": r["day"], "count": r["cnt"]} for r in rows]

            # 4. Peak Usage Hours
            rows = await conn.fetch(
                "SELECT CAST(substring(created_at from 12 for 2) AS INTEGER) as hour, COUNT(*) as cnt "
                "FROM query_analytics GROUP BY hour ORDER BY hour"
            )
            peak_hours = [{"hour": r["hour"], "count": r["cnt"]} for r in rows]

            # 5. Recent Activity Feed
            rows = await conn.fetch(
                "SELECT question, sources_found, answered, response_ms, user_id, created_at "
                "FROM query_analytics ORDER BY created_at DESC LIMIT 20"
            )
            recent_activity = [
                {"question": r["question"], "sources_found": r["sources_found"],
                 "answered": bool(r["answered"]),
                 "response_ms": r["response_ms"], "user_id": r["user_id"],
                 "created_at": r["created_at"]}
                for r in rows
            ]

            # 6. Response Time stats
            row = await conn.fetchrow(
                "SELECT AVG(response_ms)::int as avg_ms, MIN(response_ms) as min_ms, "
                "MAX(response_ms) as max_ms FROM query_analytics WHERE response_ms IS NOT NULL"
            )
            response_time = {
                "avg_ms": row["avg_ms"] or 0,
                "min_ms": row["min_ms"] or 0,
                "max_ms": row["max_ms"] or 0,
            }

            # 7. Space Usage Breakdown
            rows = await conn.fetch(
                "SELECT space_keys, COUNT(*) as cnt FROM query_analytics "
                "WHERE space_keys IS NOT NULL AND space_keys != '' "
                "GROUP BY space_keys ORDER BY cnt DESC LIMIT 15"
            )
            space_usage = [{"space_keys": r["space_keys"], "count": r["cnt"]} for r in rows]

            # 9. Per-User Usage
            rows = await conn.fetch(
                "SELECT user_id, COUNT(*) as cnt FROM query_analytics "
                "WHERE user_id IS NOT NULL GROUP BY user_id ORDER BY cnt DESC LIMIT 10"
            )
            per_user = [{"user_id": r["user_id"], "count": r["cnt"]} for r in rows]

            # Active users in last 24h
            cutoff_24h = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
            active_users_24h = await conn.fetchval(
                "SELECT COUNT(DISTINCT user_id) FROM query_analytics "
                "WHERE user_id IS NOT NULL AND created_at > $1", cutoff_24h
            )

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
        if max_age_days <= 0:
            return 0
        cutoff = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).isoformat()
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM conversations WHERE updated_at < $1", cutoff
            )
        count = int(result.split()[-1])  # "DELETE N"
        if count:
            logger.info("Pruned %d conversations older than %d days", count, max_age_days)
        return count

    # ── Graph RAG ─────────────────────────────────────────────────────────────

    async def upsert_page_links(self, from_page_id: str, to_page_ids: list[str]) -> None:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "DELETE FROM page_links WHERE from_page_id = $1", from_page_id
                )
                if to_page_ids:
                    await conn.executemany(
                        "INSERT INTO page_links (from_page_id, to_page_id) VALUES ($1, $2) "
                        "ON CONFLICT DO NOTHING",
                        [(from_page_id, to_id) for to_id in to_page_ids],
                    )

    async def get_linked_page_ids(self, page_ids: list[str]) -> list[str]:
        if not page_ids:
            return []
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT DISTINCT to_page_id FROM page_links WHERE from_page_id = ANY($1::text[])",
                page_ids,
            )
        already = set(page_ids)
        return [r["to_page_id"] for r in rows if r["to_page_id"] not in already]

    # ── GDPR / Data Purge ─────────────────────────────────────────────────────

    async def purge_user_data(self, user_id: str) -> dict:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                conv_count = await conn.fetchval(
                    "SELECT COUNT(*) FROM conversations WHERE user_id = $1", user_id
                )
                msg_count = await conn.fetchval(
                    "SELECT COUNT(*) FROM messages WHERE conversation_id IN "
                    "(SELECT id FROM conversations WHERE user_id = $1)", user_id
                )
                feedback_count = await conn.fetchval(
                    "SELECT COUNT(*) FROM feedback WHERE conversation_id IN "
                    "(SELECT id FROM conversations WHERE user_id = $1)", user_id
                )
                await conn.execute(
                    "DELETE FROM feedback WHERE conversation_id IN "
                    "(SELECT id FROM conversations WHERE user_id = $1)", user_id
                )
                await conn.execute(
                    "DELETE FROM conversations WHERE user_id = $1", user_id
                )
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
        """GDPR right of access — export ALL data for a user."""
        async with self._pool.acquire() as conn:
            conv_rows = await conn.fetch(
                "SELECT id, title, created_at, updated_at FROM conversations WHERE user_id = $1",
                user_id,
            )
            conversations = []
            for c in conv_rows:
                conv = dict(c)
                msg_rows = await conn.fetch(
                    "SELECT id, role, content, created_at FROM messages "
                    "WHERE conversation_id = $1 ORDER BY created_at",
                    c["id"],
                )
                conv["messages"] = [dict(m) for m in msg_rows]
                fb_rows = await conn.fetch(
                    "SELECT message_id, value, created_at FROM feedback "
                    "WHERE conversation_id = $1",
                    c["id"],
                )
                conv["feedback"] = [dict(f) for f in fb_rows]
                conversations.append(conv)

        return {
            "user_id": user_id,
            "exported_at": _now_iso(),
            "conversations_count": len(conversations),
            "conversations": conversations,
        }
