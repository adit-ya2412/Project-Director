"""Asset — reusable media, with full acquisition provenance (M6)."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class AssetModel(Base):
    __tablename__ = "asset"
    __table_args__ = (
        # Dedup is per-project, not global: two different projects that
        # both happen to download the same Wikimedia photo should each get
        # their own Asset row (provenance and confidence scoring are
        # project-specific). A bare global unique=True on content_hash
        # would make the second project's insert fail outright.
        UniqueConstraint("project_id", "content_hash", name="uq_asset_project_content_hash"),
    )

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
    content_hash: Mapped[str] = mapped_column(String, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    retrieved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
