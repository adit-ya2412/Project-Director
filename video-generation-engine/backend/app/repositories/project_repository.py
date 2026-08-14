"""Project persistence.

`InMemoryProjectRepository` is process-lifetime only, kept as the fast
unit-test double (Testing Strategy: unit tests never touch external
services). `PostgresProjectRepository` (M2) is the real implementation -
callers depend on the `ProjectRepository` protocol, never on either
concrete class.
"""

import asyncio
import uuid
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import utcnow
from app.models.project import ProjectModel
from app.models.script import ScriptModel
from app.models.timeline_version import TimelineVersionModel
from app.schemas.project import Project, ProjectStatus
from app.schemas.timeline import Timeline


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


class PostgresProjectRepository:
    """Real persistence for Project + (embedded) Script + Timeline.

    Script and Timeline get their own tables (matching the full data
    model) but M2 does not yet enforce the M3 versioning discipline
    (`append_version` as the sole writer, immutability). This repository
    appends a new row only when the incoming content actually differs
    from what is already stored, and always treats the highest version
    number as current - a real `TimelineService` replaces this in M3.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, name: str) -> Project:
        model = ProjectModel(name=name, status=ProjectStatus.CREATED.value)
        self._session.add(model)
        await self._session.commit()
        await self._session.refresh(model)
        return self._to_schema(model, script=None, timeline_row=None)

    async def get(self, project_id: str) -> Project | None:
        try:
            pk = uuid.UUID(project_id)
        except ValueError:
            # Not a well-formed UUID -> can't possibly match a row. Same
            # externally-visible outcome as "not found", not an error.
            return None
        model = await self._session.get(ProjectModel, pk)
        if model is None:
            return None
        script = await self._latest_script(model.id)
        timeline_row = await self._latest_timeline_version(model.id)
        return self._to_schema(model, script=script, timeline_row=timeline_row)

    async def update(self, project: Project) -> Project:
        model = await self._session.get(ProjectModel, uuid.UUID(project.id))
        if model is None:
            raise ValueError(f"project {project.id} does not exist")

        model.status = project.status.value
        model.error = project.error
        model.video_path = project.video_path

        if project.script is not None:
            await self._append_script_if_changed(model.id, project.script)

        if project.timeline is not None:
            await self._append_timeline_if_changed(model, project.timeline)

        await self._session.commit()
        await self._session.refresh(model)

        project.updated_at = model.updated_at
        return project

    async def list_all(self) -> list[Project]:
        result = await self._session.execute(select(ProjectModel))
        projects = []
        for model in result.scalars().all():
            script = await self._latest_script(model.id)
            timeline_row = await self._latest_timeline_version(model.id)
            projects.append(self._to_schema(model, script=script, timeline_row=timeline_row))
        return projects

    # -- internals ---------------------------------------------------

    async def _latest_script(self, project_id: uuid.UUID) -> ScriptModel | None:
        result = await self._session.execute(
            select(ScriptModel)
            .where(ScriptModel.project_id == project_id)
            .order_by(ScriptModel.version.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _latest_timeline_version(self, project_id: uuid.UUID) -> TimelineVersionModel | None:
        result = await self._session.execute(
            select(TimelineVersionModel)
            .where(TimelineVersionModel.project_id == project_id)
            .order_by(TimelineVersionModel.version.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _append_script_if_changed(self, project_id: uuid.UUID, content: str) -> None:
        existing = await self._latest_script(project_id)
        if existing is not None and existing.content == content:
            return
        next_version = (existing.version + 1) if existing else 1
        self._session.add(ScriptModel(project_id=project_id, content=content, version=next_version))

    async def _append_timeline_if_changed(self, model: ProjectModel, timeline: Timeline) -> None:
        document = timeline.model_dump(mode="json")
        existing = await self._latest_timeline_version(model.id)
        if existing is not None and existing.document == document:
            return
        self._session.add(
            TimelineVersionModel(
                project_id=model.id,
                version=timeline.version,
                parent_version=timeline.parent_version,
                produced_by=timeline.produced_by.value,
                status=timeline.status.value,
                document=document,
            )
        )
        model.active_timeline_version = timeline.version

    @staticmethod
    def _to_schema(
        model: ProjectModel,
        *,
        script: ScriptModel | None,
        timeline_row: TimelineVersionModel | None,
    ) -> Project:
        return Project(
            id=str(model.id),
            name=model.name,
            status=ProjectStatus(model.status),
            script=script.content if script else None,
            timeline=Timeline.model_validate(timeline_row.document) if timeline_row else None,
            video_path=model.video_path,
            error=model.error,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )
