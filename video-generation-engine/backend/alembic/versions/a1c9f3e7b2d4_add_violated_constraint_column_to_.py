"""add violated_constraint column to generated_clip for M6.5 constraint enforcement

Revision ID: a1c9f3e7b2d4
Revises: f0383fda7dc7
Create Date: 2026-08-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1c9f3e7b2d4'
down_revision: Union[str, None] = 'f0383fda7dc7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('generated_clip', sa.Column('violated_constraint', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('generated_clip', 'violated_constraint')
