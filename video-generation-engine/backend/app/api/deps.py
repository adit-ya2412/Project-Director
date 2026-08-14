"""Request-scoped dependencies.

`get_repo` is the seam: swapping the backing store (M0's in-memory dict,
M2's Postgres) never touches a route handler, because every handler
depends on the `ProjectRepository` protocol via this function.

`get_timeline_service` and `get_workflow_engine` share the same
request-scoped session as `get_repo` (all resolve through `get_db`,
which FastAPI caches per-request), so a route that needs several sees
one consistent transaction.
"""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.repositories.project_repository import PostgresProjectRepository
from app.timeline.service import TimelineService
from app.workflow.context import RunContext
from app.workflow.engine import WorkflowEngine


def get_repo(session: Annotated[AsyncSession, Depends(get_db)]) -> PostgresProjectRepository:
    return PostgresProjectRepository(session)


def get_timeline_service(session: Annotated[AsyncSession, Depends(get_db)]) -> TimelineService:
    return TimelineService(session)


def get_workflow_engine(
    project_id: str,
    session: Annotated[AsyncSession, Depends(get_db)],
    repo: Annotated[PostgresProjectRepository, Depends(get_repo)],
    timeline_service: Annotated[TimelineService, Depends(get_timeline_service)],
) -> WorkflowEngine:
    ctx = RunContext(
        project_id=project_id, session=session, repo=repo, timeline_service=timeline_service
    )
    return WorkflowEngine(ctx)
