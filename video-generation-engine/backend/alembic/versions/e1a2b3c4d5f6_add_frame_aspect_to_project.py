"""add frame_aspect on project (stillness 9:16 reel)

Revision ID: e1a2b3c4d5f6
Revises: d9e1a4c7b8f0
Create Date: 2026-08-21 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e1a2b3c4d5f6"
down_revision: Union[str, None] = "d9e1a4c7b8f0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("project", sa.Column("frame_aspect", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("project", "frame_aspect")
