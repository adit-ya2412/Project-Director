"""add secondary_state / secondary_last_error on shot_binding (R18)

Revision ID: c8f5d3b02e19
Revises: b7e4c2a91d08
Create Date: 2026-08-20 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c8f5d3b02e19"
down_revision: Union[str, None] = "b7e4c2a91d08"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("shot_binding", sa.Column("secondary_state", sa.String(), nullable=True))
    op.add_column("shot_binding", sa.Column("secondary_last_error", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("shot_binding", "secondary_last_error")
    op.drop_column("shot_binding", "secondary_state")
