"""initial schema — matches pg_conversation_store._SCHEMA

Revision ID: 001_initial
Revises: None
Create Date: 2026-04-16
"""
from typing import Sequence, Union

from alembic import op

revision: str = "001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
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
            indexed_at    TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS query_analytics (
            id            TEXT PRIMARY KEY,
            question      TEXT NOT NULL,
            sources_found INTEGER NOT NULL DEFAULT 0,
            answered      INTEGER NOT NULL DEFAULT 1,
            created_at    TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_analytics_created ON query_analytics(created_at);

        CREATE TABLE IF NOT EXISTS page_links (
            from_page_id TEXT NOT NULL,
            to_page_id   TEXT NOT NULL,
            PRIMARY KEY (from_page_id, to_page_id)
        );

        CREATE INDEX IF NOT EXISTS idx_page_links_from ON page_links(from_page_id);
    """)


def downgrade() -> None:
    op.execute("""
        DROP TABLE IF EXISTS page_links;
        DROP TABLE IF EXISTS query_analytics;
        DROP TABLE IF EXISTS page_index;
        DROP TABLE IF EXISTS feedback;
        DROP TABLE IF EXISTS messages;
        DROP TABLE IF EXISTS conversations;
    """)
