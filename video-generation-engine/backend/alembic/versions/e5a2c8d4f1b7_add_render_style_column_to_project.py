"""add render_style column to project for script pre-planning style choice

Revision ID: e5a2c8d4f1b7
Revises: d3f8a1b6c9e2
Create Date: 2026-08-17 00:00:01.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5a2c8d4f1b7'
down_revision: Union[str, None] = 'd3f8a1b6c9e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'project',
        sa.Column('render_style', sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('project', 'render_style')
