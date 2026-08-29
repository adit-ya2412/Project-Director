"""llm_call: nullable cost_cents + rate columns (OQ-4.4)

Revision ID: a8b3c1d4e5f6
Revises: f7c1d9a3b2e4
Create Date: 2026-08-29 00:00:00.000000

cost_cents was Integer NOT NULL default 0, so an unknown model could not
be stored as NULL (looked free). Make it nullable and persist the
USD-per-1M rates used at insert time so a later price-table change does
not rewrite history.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a8b3c1d4e5f6"
down_revision: Union[str, None] = "f7c1d9a3b2e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "llm_call",
        "cost_cents",
        existing_type=sa.Integer(),
        nullable=True,
    )
    op.add_column(
        "llm_call",
        sa.Column("input_usd_per_1m", sa.Float(), nullable=True),
    )
    op.add_column(
        "llm_call",
        sa.Column("output_usd_per_1m", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("llm_call", "output_usd_per_1m")
    op.drop_column("llm_call", "input_usd_per_1m")
    op.execute("UPDATE llm_call SET cost_cents = 0 WHERE cost_cents IS NULL")
    op.alter_column(
        "llm_call",
        "cost_cents",
        existing_type=sa.Integer(),
        nullable=False,
    )
