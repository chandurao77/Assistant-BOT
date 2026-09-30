"""Add space_key to page_index

Revision ID: 003
Revises: 002
Create Date: 2026-06-09
"""
from alembic import op
import sqlalchemy as sa

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("page_index") as batch_op:
        batch_op.add_column(sa.Column("space_key", sa.Text(), nullable=False, server_default=""))
    op.create_index("idx_page_index_space", "page_index", ["space_key"])


def downgrade() -> None:
    op.drop_index("idx_page_index_space", table_name="page_index")
    with op.batch_alter_table("page_index") as batch_op:
        batch_op.drop_column("space_key")
