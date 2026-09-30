"""Add reason columns to feedback table.

Revision ID: 002
Revises: 001
"""

revision = "002"
down_revision = "001"

_UPGRADE_SQL = """
    ALTER TABLE feedback ADD COLUMN reason TEXT DEFAULT NULL;
    ALTER TABLE feedback ADD COLUMN reason_text TEXT DEFAULT NULL;
"""

# SQLite doesn't support DROP COLUMN in older versions, so downgrade
# just leaves the columns in place (harmless).
_DOWNGRADE_SQL = ""


def upgrade(op):
    for stmt in _UPGRADE_SQL.strip().split(";"):
        stmt = stmt.strip()
        if stmt:
            op.execute(stmt)


def downgrade(op):
    pass
