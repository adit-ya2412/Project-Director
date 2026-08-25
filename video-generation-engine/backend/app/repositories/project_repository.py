"""Project persistence.

`InMemoryProjectRepository` is process-lifetime only, kept as the fast
unit-test double (Testing Strategy: unit tests never touch external
services). `PostgresProjectRepository` (M2) is the real implementation -
callers depend on the `ProjectRepository` protocol, never on either
concrete class.

`PostgresProjectRepository` only ever *reads* `timeline_version` (via
`TimelineVersionRepository`) - it never writes one. `TimelineService`
(app/timeline/service.py) is the only writer, per Invariant I3. If you
find yourself adding a `timeline_version` insert here, that belongs in
`TimelineService.append_version` instead.
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
from app.repositories.timeline_repository import TimelineVersionRepository
from app.schemas.project import Project, ProjectStatus
from app.schemas.timeline import Timeline


class ProjectRepository(Protocol):
    async def create(
        self,
        name: str,
        render_style: str | None = None,
        frame_aspect: str | None = None,
        language_code: str | None = None,
    ) -> Project: ...
    async def get(self, project_id: str) -> Project | None: ...
    async def update(self, project: Project) -> Project: ...
    async def list_all(self) -> list[Project]: ...
    async def append_rewritten_script(self, project_id: str, content: str) -> Project: ...


class InMemoryProjectRepository:
    def __init__(self) -> None:
        self._projects: dict[str, Project] = {}
        self._lock = asyncio.Lock()

    async def create(
        self,
        name: str,
        render_style: str | None = None,
        frame_aspect: str | None = None,
        language_code: str | None = None,
    ) -> Project:
        project = Project(
            name=name,
            render_style=render_style,
            frame_aspect=frame_aspect,
            language_code=language_code,
        )
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

    async def append_rewritten_script(self, project_id: str, content: str) -> Project:
        # No version history here (this double doesn't model `ScriptModel`
        # at all - it holds `Project.script` as a plain field) - good
        # enough for the unit tests this class exists for, which never
        # assert on script provenance/versioning.
        async with self._lock:
            project = self._projects[project_id]
        project.script = content
        return await self.update(project)


class PostgresProjectRepository:
    """Real persistence for Project + Script + (read-only) Timeline."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._timeline_repo = TimelineVersionRepository(session)

    async def create(
        self,
        name: str,
        render_style: str | None = None,
        frame_aspect: str | None = None,
        language_code: str | None = None,
    ) -> Project:
        model = ProjectModel(
            name=name,
            status=ProjectStatus.CREATED.value,
            render_style=render_style,
            frame_aspect=frame_aspect,
            language_code=language_code,
        )
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
        timeline_row = await self._timeline_repo.get_latest(model.id)
        return self._to_schema(model, script=script, timeline_row=timeline_row)

    async def update(self, project: Project) -> Project:
        """Updates status/error/video_path, and appends a new script
        version if the content changed. Does NOT write the Timeline -
        that goes through `TimelineService` only. The returned Project
        always reflects the current DB state, not just an echo of what
        the caller passed in."""
        model = await self._session.get(ProjectModel, uuid.UUID(project.id))
        if model is None:
            raise ValueError(f"project {project.id} does not exist")

        model.status = project.status.value
        model.error = project.error
        model.video_path = project.video_path
        # Unconditional overwrite, unlike `script` below - `render_style`
        # is pre-planning staging, not audit-trail content (Track B), so
        # it needs no version history of its own; `None` here simply
        # means the caller didn't touch it this call, not "clear it".
        if project.render_style is not None:
            model.render_style = project.render_style
        # None is a real value here too, same reason as frame_aspect right
        # below (2026-08-25, `set_language`'s own endpoint needs to be able
        # to explicitly CLEAR a language hint, not just set one) - every
        # caller of `update()` fetched this Project via `get()` first
        # (`_to_schema` always populates the CURRENT DB value), so `None`
        # here always means "clear it", never "this caller didn't touch
        # it" the way a fresh, never-fetched Project's default would.
        model.language_code = project.language_code
        # None is a real value here (stillness default 16:9, or a
        # non-stillness style that cannot carry an override). Always
        # write, unlike render_style above.
        model.frame_aspect = project.frame_aspect

        if project.script is not None:
            await self._append_script_if_changed(model.id, project.script)

        await self._session.commit()
        await self._session.refresh(model)

        script = await self._latest_script(model.id)
        timeline_row = await self._timeline_repo.get_latest(model.id)
        return self._to_schema(model, script=script, timeline_row=timeline_row)

    async def list_all(self) -> list[Project]:
        result = await self._session.execute(select(ProjectModel))
        projects = []
        for model in result.scalars().all():
            script = await self._latest_script(model.id)
            timeline_row = await self._timeline_repo.get_latest(model.id)
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

    async def _append_script_if_changed(
        self, project_id: uuid.UUID, content: str, *, source: str = "user"
    ) -> None:
        existing = await self._latest_script(project_id)
        if existing is not None and existing.content == content:
            return
        next_version = (existing.version + 1) if existing else 1
        self._session.add(
            ScriptModel(project_id=project_id, content=content, version=next_version, source=source)
        )

    async def append_rewritten_script(self, project_id: str, content: str) -> Project:
        """Persists a Track D level-3 rewrite result (plan §3.5) as a new
        `ScriptModel` version with `source="rewritten"` - deliberately
        NOT routed through `update()` above, which always writes
        `source="user"` implicitly (the correct default for every other
        caller). This is the one path that needs to say otherwise."""
        model = await self._session.get(ProjectModel, uuid.UUID(project_id))
        if model is None:
            raise ValueError(f"project {project_id} does not exist")
        await self._append_script_if_changed(model.id, content, source="rewritten")
        await self._session.commit()
        await self._session.refresh(model)
        script = await self._latest_script(model.id)
        timeline_row = await self._timeline_repo.get_latest(model.id)
        return self._to_schema(model, script=script, timeline_row=timeline_row)

    @staticmethod
    def _to_schema(
        model: ProjectModel,
        *,
        script: ScriptModel | None,
        timeline_row: TimelineVersionModel | None,
    ) -> Project:
        timeline = Timeline.model_validate(timeline_row.document) if timeline_row else None
        if timeline is not None:
            style = timeline.metadata.render_style or model.render_style
            aspect = timeline.metadata.frame_aspect
        else:
            style = model.render_style
            aspect = model.frame_aspect
        from app.script.styles import resolve_render_format

        frame = resolve_render_format(style, frame_aspect=aspect)
        return Project(
            id=str(model.id),
            name=model.name,
            status=ProjectStatus(model.status),
            script=script.content if script else None,
            render_style=model.render_style,
            frame_aspect=aspect,
            language_code=model.language_code,
            render_width=frame.width,
            render_height=frame.height,
            timeline=timeline,
            video_path=model.video_path,
            error=model.error,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )
