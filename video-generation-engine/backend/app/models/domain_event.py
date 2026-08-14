"""DomainEvent — append-only log (docs/08_Workflow_Engine.md, Events).

Substrate for progress reporting, debugging, and any future distributed
execution. Never updated or deleted, only inserted.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class DomainEventModel(Base):
    __tablename__ = "domain_event"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project.id"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    # e.g. TimelineGenerated, ShotPlanned, AssetResolved, RenderCompleted
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
