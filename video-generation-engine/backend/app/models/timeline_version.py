"""TimelineVersion — canon 3.3: stored as a single JSONB document per
version, not normalized scene/shot rows. Versioning is a row insert;
rollback is a pointer update; the IR schema evolves without migrations.

M2 persists this table so a Timeline survives a restart. M3 (Timeline
Service) adds the append-only discipline: `append_version` is the only
writer, and no other code path may touch this table directly.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class TimelineVersionModel(Base):
    __tablename__ = "timeline_version"
    __table_args__ = (
        UniqueConstraint("project_id", "version", name="uq_timeline_project_version"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project.id"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    produced_by: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="draft")
    document: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
