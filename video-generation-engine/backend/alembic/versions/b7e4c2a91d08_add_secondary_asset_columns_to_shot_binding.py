"""add secondary asset/clip columns on shot_binding for split-screen

Revision ID: b7e4c2a91d08
Revises: e5a2c8d4f1b7
Create Date: 2026-08-20 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b7e4c2a91d08"
down_revision: Union[str, None] = "e5a2c8d4f1b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "shot_binding",
        sa.Column("secondary_asset_id", sa.UUID(), nullable=True),
    )
    op.add_column(
        "shot_binding",
        sa.Column("secondary_clip_id", sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        "fk_shot_binding_secondary_asset_id",
        "shot_binding",
        "asset",
        ["secondary_asset_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_shot_binding_secondary_clip_id",
        "shot_binding",
        "generated_clip",
        ["secondary_clip_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_shot_binding_secondary_clip_id", "shot_binding", type_="foreignkey")
    op.drop_constraint("fk_shot_binding_secondary_asset_id", "shot_binding", type_="foreignkey")
    op.drop_column("shot_binding", "secondary_clip_id")
    op.drop_column("shot_binding", "secondary_asset_id")
