"""add is_draft on render (§19.9)

Revision ID: d9e1a4c7b8f0
Revises: c8f5d3b02e19
Create Date: 2026-08-21 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d9e1a4c7b8f0"
down_revision: Union[str, None] = "c8f5d3b02e19"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "render",
        sa.Column("is_draft", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    # Backfill: yesterday's drafts were identified by the 480×854 pair.
    op.execute("UPDATE render SET is_draft = true WHERE width = 480 AND height = 854")


def downgrade() -> None:
    op.drop_column("render", "is_draft")
