"""add language_code on project (ElevenLabs code-switch hint)

Revision ID: f7c1d9a3b2e4
Revises: e1a2b3c4d5f6
Create Date: 2026-08-24 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f7c1d9a3b2e4"
down_revision: Union[str, None] = "e1a2b3c4d5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("project", sa.Column("language_code", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("project", "language_code")
