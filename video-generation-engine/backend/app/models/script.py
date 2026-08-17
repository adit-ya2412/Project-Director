"""Script — immutable, versioned user input."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class ScriptModel(Base):
    __tablename__ = "script"
    __table_args__ = (UniqueConstraint("project_id", "version", name="uq_script_project_version"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project.id"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str] = mapped_column(String, nullable=False, default="en")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # "user" | "rewritten" (script pre-flight, motion_new_styles_and_
    # long_form_videos.md §3.5). This is the ONLY new column the feature
    # needed - the rest of the design it originally called for
    # (script_original/script_source on Project) turned out to duplicate
    # this table's own versioning, which already gives full history
    # ("the original" is simply version 1, already queryable) rather than
    # the one-level-back the original design would have kept.
    source: Mapped[str] = mapped_column(String, nullable=False, default="user")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
