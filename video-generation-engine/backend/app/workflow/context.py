"""Everything a WorkflowStep needs to do its job, without depending
directly on FastAPI's DI or any specific caller."""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.project_repository import ProjectRepository
from app.timeline.service import TimelineService


@dataclass
class RunContext:
    project_id: str
    session: AsyncSession
    repo: ProjectRepository
    timeline_service: TimelineService
