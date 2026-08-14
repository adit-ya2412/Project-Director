"""Asset — reusable media, with full acquisition provenance (M6)."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class AssetModel(Base):
    __tablename__ = "asset"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project.id"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String, nullable=False)
    source_url: Mapped[str | None] = mapped_column(String, nullable=True)
    type: Mapped[str] = mapped_column(String, nullable=False)  # image | video
    local_path: Mapped[str | None] = mapped_column(String, nullable=True)
    licence: Mapped[str] = mapped_column(String, nullable=False, default="unknown")
    attribution: Mapped[str | None] = mapped_column(String, nullable=True)
    # Dedup key (M6 advice): the same photo arrives from multiple providers
    # under different URLs; hash the bytes, not the URL.
    content_hash: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    retrieved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
