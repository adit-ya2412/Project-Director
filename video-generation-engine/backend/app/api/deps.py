"""Request-scoped dependencies.

`get_repo` is the seam: swapping the backing store (M0's in-memory dict,
M2's Postgres) never touches a route handler, because every handler
depends on the `ProjectRepository` protocol via this function.

`get_timeline_service` shares the same request-scoped session as
`get_repo` (both resolve through `get_db`), so a route that needs both
sees one consistent transaction.
"""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.repositories.project_repository import PostgresProjectRepository
from app.timeline.service import TimelineService


def get_repo(session: Annotated[AsyncSession, Depends(get_db)]) -> PostgresProjectRepository:
    return PostgresProjectRepository(session)


def get_timeline_service(session: Annotated[AsyncSession, Depends(get_db)]) -> TimelineService:
    return TimelineService(session)
