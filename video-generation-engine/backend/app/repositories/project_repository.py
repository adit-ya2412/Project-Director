"""Project persistence.

M0/M1: in-memory only, process-lifetime. M2 replaces this with a
Postgres-backed repository behind the same interface (implementation
guide, Phase M2) — callers depend on `ProjectRepository`, never on the
concrete in-memory dict.
"""

import asyncio
from typing import Protocol

from app.core.clock import utcnow
from app.schemas.project import Project


class ProjectRepository(Protocol):
    async def create(self, name: str) -> Project: ...
    async def get(self, project_id: str) -> Project | None: ...
    async def update(self, project: Project) -> Project: ...
    async def list_all(self) -> list[Project]: ...


class InMemoryProjectRepository:
    def __init__(self) -> None:
        self._projects: dict[str, Project] = {}
        self._lock = asyncio.Lock()

    async def create(self, name: str) -> Project:
        project = Project(name=name)
        async with self._lock:
            self._projects[project.id] = project
        return project

    async def get(self, project_id: str) -> Project | None:
        async with self._lock:
            return self._projects.get(project_id)

    async def update(self, project: Project) -> Project:
        project.updated_at = utcnow()
        async with self._lock:
            self._projects[project.id] = project
        return project

    async def list_all(self) -> list[Project]:
        async with self._lock:
            return list(self._projects.values())
