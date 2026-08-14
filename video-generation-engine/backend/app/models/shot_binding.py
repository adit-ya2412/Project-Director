"""ShotBinding — mutable per-shot execution state (implementation guide
section 6.3). This is the answer to "where did the media go", and the
reason the Timeline itself stays clean of file paths.

`SELECT * FROM shot_binding WHERE state = 'pending'` is the media
generation work queue (M7). Partial regeneration = reset one row and
re-run (M9).
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class ShotBindingModel(Base):
    __tablename__ = "shot_binding"
    __table_args__ = (
        # One binding per shot per timeline version. A later version that
        # changes a shot's content gets a fresh pending row rather than
        # inheriting a possibly-stale resolved asset (simple first - see
        # implementation guide M4 notes on why this isn't versionless).
        UniqueConstraint(
            "project_id", "timeline_version", "shot_id", name="uq_shot_binding_project_version_shot"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project.id"), nullable=False
    )
    timeline_version: Mapped[int] = mapped_column(Integer, nullable=False)
    shot_id: Mapped[str] = mapped_column(String, nullable=False)
    state: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    # pending | searching | resolved | generating | generated | failed | skipped
    asset_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("asset.id"), nullable=True
    )
    clip_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("generated_clip.id"), nullable=True
    )
    rung: Mapped[str | None] = mapped_column(String, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(String, nullable=True)
    cost_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
