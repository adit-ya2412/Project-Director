"""Project — the aggregate root (Domain Model doc)."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class ProjectModel(Base):
    __tablename__ = "project"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="created")
    # Canon 3.2: a project has many Timeline versions, at most one active.
    active_timeline_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(String, nullable=True)
    video_path: Mapped[str | None] = mapped_column(String, nullable=True)
    # `NULL` = "no style chosen, use settings.default_render_style" -
    # motion_new_styles_and_long_form_videos.md, Track B (2026-08-17).
    # Pre-planning STAGING only: `TimelineService.create_initial` copies
    # this into `Timeline.metadata.render_style` once, at v1, which
    # becomes the real, frozen record from then on (I1) - this column is
    # never read again after that point. Settable only before a Timeline
    # exists (same freeze check `upload_script` already enforces for the
    # script itself), since a style choice affecting Shot Planner
    # fragment-granularity decisions cannot be safely changed once
    # planning has started.
    render_style: Mapped[str | None] = mapped_column(String, nullable=True)
    # Stillness-only 9:16 reel vs 16:9 default. Frozen onto the Timeline
    # at create_initial, same as render_style.
    frame_aspect: Mapped[str | None] = mapped_column(String, nullable=True)
    # ISO 639-1 hint for ElevenLabs' `language_code` param (2026-08-24,
    # hinglish_voice_probe.py) - a code-switched (Hindi/Hinglish,
    # Spanish/Spanglish, ...) script's narration otherwise stalls at
    # every language-switch boundary on the default model's own
    # detection. `None` = no hint (most projects need none). Frozen onto
    # the Timeline at create_initial, same as render_style/frame_aspect;
    # `POST /narration/retry-language` corrects it after the fact for a
    # project that already has a timeline.
    language_code: Mapped[str | None] = mapped_column(String, nullable=True)
    # timezone=True: app.core.clock.utcnow() is tz-aware UTC everywhere else
    # in the app; a naive column would silently drop that on write.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
