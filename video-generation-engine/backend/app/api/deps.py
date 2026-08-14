"""Request-scoped dependencies.

`get_repo` is the seam: swapping the backing store (M0's in-memory dict,
M2's Postgres) never touches a route handler, because every handler
depends on the `ProjectRepository` protocol via this function.
"""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.repositories.project_repository import PostgresProjectRepository


def get_repo(session: Annotated[AsyncSession, Depends(get_db)]) -> PostgresProjectRepository:
    return PostgresProjectRepository(session)
