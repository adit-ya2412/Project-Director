"""add description column to asset for M6.5 upload matching

Revision ID: c7d2a8e91f3b
Revises: a1c9f3e7b2d4
Create Date: 2026-08-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c7d2a8e91f3b'
down_revision: Union[str, None] = 'a1c9f3e7b2d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('asset', sa.Column('description', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('asset', 'description')
