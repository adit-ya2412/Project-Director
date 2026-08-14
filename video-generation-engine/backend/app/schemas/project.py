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
    RENDERING = "rendering"
    COMPLETED = "completed"
    FAILED = "failed"


class Project(BaseModel):
    id: str = Field(default_factory=new_id_str)
    name: str
    status: ProjectStatus = ProjectStatus.CREATED
    script: str | None = None
    timeline: Timeline | None = None
    video_path: str | None = None
    error: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
