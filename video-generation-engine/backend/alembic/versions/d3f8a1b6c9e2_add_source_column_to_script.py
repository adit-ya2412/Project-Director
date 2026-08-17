"""add source column to script for script pre-flight rewrite provenance

Revision ID: d3f8a1b6c9e2
Revises: c7d2a8e91f3b
Create Date: 2026-08-17 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd3f8a1b6c9e2'
down_revision: Union[str, None] = 'c7d2a8e91f3b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'script',
        sa.Column('source', sa.String(), nullable=False, server_default='user'),
    )


def downgrade() -> None:
    op.drop_column('script', 'source')
