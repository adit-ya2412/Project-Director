"""Project — the aggregate root (Domain Model doc, section "Aggregate Root").

M0 keeps this as a plain Pydantic model held in memory. M2 replaces the
storage with Postgres behind the same repository interface; this shape is
expected to survive that move largely unchanged.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from app.core.clock import utcnow
from app.core.ids import new_id_str
from app.schemas.timeline import Timeline


class ProjectStatus(StrEnum):
    CREATED = "created"
    SCRIPT_UPLOADED = "script_uploaded"
    AWAITING_APPROVAL = "awaiting_approval"
    # A28 (M6.5): the A15/A26 generated-media review gate is a DIFFERENT
    # question from AWAITING_APPROVAL ("approve the creative plan") and
    # gets its own status, so a human arriving at a stopped project can
    # tell which remedy applies - re-approving a plan does nothing for a
    # shot that failed generation, and overriding a shot does nothing for
    # an unapproved plan.
    AWAITING_REVIEW = "awaiting_review"
    RENDERING = "rendering"
    COMPLETED = "completed"
    FAILED = "failed"


class Project(BaseModel):
    id: str = Field(default_factory=new_id_str)
    name: str
    status: ProjectStatus = ProjectStatus.CREATED
    script: str | None = None
    # Pre-planning style staging (Track B, 2026-08-17) - see
    # `ProjectModel.render_style`'s own docstring for the full contract;
    # `None` means "use settings.default_render_style".
    render_style: str | None = None
    frame_aspect: str | None = None
    # ISO 639-1 hint for ElevenLabs' `language_code` param, staged the
    # same way as render_style/frame_aspect - see `ProjectModel
    # .language_code`'s own docstring for the full contract.
    language_code: str | None = None
    render_width: int | None = None
    render_height: int | None = None
    timeline: Timeline | None = None
    video_path: str | None = None
    error: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
