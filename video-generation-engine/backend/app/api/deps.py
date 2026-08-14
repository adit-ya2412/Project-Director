"""Request-scoped dependencies.

M0 holds a single process-lifetime repository on `app.state`. M2 replaces
this with a real DB session dependency behind the same `get_repo` seam.
"""

from fastapi import Request

from app.repositories.project_repository import InMemoryProjectRepository


def get_repo(request: Request) -> InMemoryProjectRepository:
    return request.app.state.project_repo
