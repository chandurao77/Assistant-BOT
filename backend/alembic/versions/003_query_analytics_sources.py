"""Add sources column to query_analytics table.

Revision ID: 003
Revises: 002
"""

revision = "003"
down_revision = "002"

_UPGRADE_SQL = """
    ALTER TABLE query_analytics ADD COLUMN sources TEXT DEFAULT NULL;
"""

# SQLite doesn't support DROP COLUMN in older versions — downgrade is a no-op.
_DOWNGRADE_SQL = ""


def upgrade(op):
    for stmt in _UPGRADE_SQL.strip().split(";"):
        stmt = stmt.strip()
        if stmt:
            op.execute(stmt)


def downgrade(op):
    pass
