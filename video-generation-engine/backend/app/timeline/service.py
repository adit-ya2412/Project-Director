"""TimelineService — the versioning discipline that makes Invariant I3
(Timeline versions are immutable) impossible to violate in code.

`append_version` is the ONLY way a new Timeline version is created. No
other code in the system should call `session.add(TimelineVersionModel(...))`
- if you find yourself doing that, route through this service instead.

## ShotBinding carry-forward lives here (M6.5, A11/A20)

`ShotBinding` rows are a different table/aggregate than `TimelineVersion`,
so carrying them forward across a version bump is a genuine design
choice, not a given from I3. It is made HERE, inside `_persist` - the one
method every version-creating path (`append_version`, `rollback_to`)
funnels through before a new version becomes visible - specifically so
that it is structurally impossible for a new version to exist without
carry-forward having been considered. An opt-in helper that callers
remember to invoke is not good enough: the day someone adds a new
version-creating path and forgets to call it, every binding at the
superseded version silently orphans, and the free-search pre-approval
pass this whole phase exists to protect gets thrown away without anyone
noticing (exactly the failure A11 names). `create_initial` doesn't need
it - there is no prior version to carry anything from.

A20's rule is per-shot, never all-or-nothing: a binding carries forward
when its `shot_id` still exists in the new version AND that shot's
acquisition-relevant fields (`prompt`, `asset_plan`) are unchanged.
Compared as parsed Pydantic values (both sides already went through the
same JSON round-trip in `append_version`), not as raw byte strings - that
is a strictly more correct interpretation of "byte-identical" than a
literal string comparison, since it can't be defeated by harmless
key-order/formatting differences that never reached the actual planning
content.
"""

import uuid
from collections.abc import Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import utcnow
from app.core.config import settings
from app.core.errors import PermanentError
from app.models.project import ProjectModel
from app.repositories.shot_binding_repository import ShotBindingRepository
from app.repositories.timeline_repository import TimelineVersionRepository
from app.schemas.timeline import (
    CreativeContext,
    ProducedBy,
    Timeline,
    TimelineMetadata,
    TimelineStatus,
)
from app.timeline.additive import find_additive_violations
from app.timeline.diff import TimelineDiff, compute_diff

# Fields the service itself owns and stamps on every write. These describe
# *which version this is*, never planning content, so they are excluded
# from the additive-only comparison rather than requiring every caller to
# declare ownership of them.
_BOOKKEEPING_FIELDS = frozenset(
    {
        "schema_version",
        "timeline_id",
        "project_id",
        "version",
        "parent_version",
        "produced_by",
        "status",
        "created_at",
    }
)


class TimelineService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = TimelineVersionRepository(session)

    # -- reads -------------------------------------------------------

    async def get_active(self, project_id: str) -> Timeline | None:
        row = await self._repo.get_latest(uuid.UUID(project_id))
        return Timeline.model_validate(row.document) if row else None

    async def get_version(self, project_id: str, version: int) -> Timeline | None:
        row = await self._repo.get_by_version(uuid.UUID(project_id), version)
        return Timeline.model_validate(row.document) if row else None

    # -- writes -------------------------------------------------------

    async def create_initial(self, project_id: str, script: str) -> Timeline:
        """Bootstrap version 1: an empty Timeline, before any planner has
        run. Real content arrives via `append_version` (the Director's
        first pass, in M5)."""
        pid = uuid.UUID(project_id)
        if await self._repo.get_latest(pid) is not None:
            raise PermanentError(f"project {project_id} already has a timeline")

        timeline = Timeline(
            timeline_id=project_id,
            project_id=project_id,
            version=1,
            parent_version=None,
            produced_by=ProducedBy.HUMAN,  # nothing AI-produced yet
            status=TimelineStatus.DRAFT,
            created_at=utcnow(),
            metadata=TimelineMetadata(language=settings.default_language),
            creative_context=CreativeContext(),
            scenes=[],
        )
        await self._persist(pid, timeline, supersede_previous=False)
        return timeline

    async def append_version(
        self,
        project_id: str,
        produced_by: ProducedBy,
        transform: Callable[[Timeline], Timeline],
        *,
        owns: frozenset[str] = frozenset(),
    ) -> Timeline:
        """Load active -> deep copy -> transform -> validate -> persist as
        version+1. `owns` is the set of top-level (or dotted) field paths
        this call is allowed to change freely; every other previously-
        populated field must come out unchanged, or this raises.
        """
        pid = uuid.UUID(project_id)
        current_row = await self._repo.get_latest(pid)
        if current_row is None:
            raise PermanentError(
                f"project {project_id} has no timeline to append to - call create_initial first"
            )
        current = Timeline.model_validate(current_row.document)

        # Deep copy before transform: the single most likely way I3 gets
        # silently broken is a transform mutating the object it was handed.
        working_copy = current.model_copy(deep=True)
        transformed = transform(working_copy)

        # Round-trip through JSON on both sides: catches drift from direct
        # attribute mutation bypassing pydantic validators, and guarantees
        # an apples-to-apples comparison (same float/enum representation).
        old_document = current.model_dump(mode="json")
        new_document = Timeline.model_validate(transformed.model_dump(mode="json")).model_dump(
            mode="json"
        )

        # Bookkeeping is the service's to set, never the transform's.
        new_document["schema_version"] = old_document["schema_version"]
        new_document["timeline_id"] = old_document["timeline_id"]
        new_document["project_id"] = old_document["project_id"]
        new_document["version"] = current.version + 1
        new_document["parent_version"] = current.version
        new_document["produced_by"] = produced_by.value
        new_document["status"] = TimelineStatus.DRAFT.value
        new_document["created_at"] = utcnow().isoformat()

        content_old = {k: v for k, v in old_document.items() if k not in _BOOKKEEPING_FIELDS}
        content_new = {k: v for k, v in new_document.items() if k not in _BOOKKEEPING_FIELDS}
        violations = find_additive_violations(content_old, content_new, owns)
        if violations:
            raise PermanentError(
                f"append_version rejected non-additive change(s) for project {project_id} "
                f"(produced_by={produced_by.value}): {violations}"
            )

        new_timeline = Timeline.model_validate(new_document)
        await self._persist(pid, new_timeline, supersede_previous=True)
        return new_timeline

    async def approve(self, project_id: str, version: int) -> Timeline:
        pid = uuid.UUID(project_id)
        row = await self._repo.get_by_version(pid, version)
        if row is None:
            raise PermanentError(f"project {project_id} has no version {version}")

        document = dict(row.document)
        document["status"] = TimelineStatus.APPROVED.value
        row.document = document
        row.status = TimelineStatus.APPROVED.value

        project = await self._session.get(ProjectModel, pid)
        if project is not None:
            project.active_timeline_version = version
        await self._session.commit()
        return Timeline.model_validate(row.document)

    async def rollback_to(self, project_id: str, version: int) -> Timeline:
        """Appends a copy of `version`'s content as a new version; never
        deletes. Rolling back from v7 to v3 creates v8 whose content
        equals v3."""
        pid = uuid.UUID(project_id)
        target_row = await self._repo.get_by_version(pid, version)
        if target_row is None:
            raise PermanentError(f"project {project_id} has no version {version} to roll back to")
        current_row = await self._repo.get_latest(pid)
        if current_row is None:
            raise PermanentError(f"project {project_id} has no active timeline")

        document = dict(target_row.document)
        document["version"] = current_row.version + 1
        document["parent_version"] = current_row.version
        document["produced_by"] = ProducedBy.HUMAN.value
        document["status"] = TimelineStatus.DRAFT.value
        document["created_at"] = utcnow().isoformat()

        rolled_back = Timeline.model_validate(document)
        await self._persist(pid, rolled_back, supersede_previous=True)
        return rolled_back

    async def diff(self, project_id: str, v_from: int, v_to: int) -> TimelineDiff:
        old = await self.get_version(project_id, v_from)
        new = await self.get_version(project_id, v_to)
        if old is None or new is None:
            raise PermanentError(f"project {project_id}: version {v_from} or {v_to} does not exist")
        return compute_diff(old, new)

    # -- internals ---------------------------------------------------

    async def _persist(
        self, project_id: uuid.UUID, timeline: Timeline, *, supersede_previous: bool
    ) -> None:
        if supersede_previous:
            previous = await self._repo.get_latest(project_id)
            if previous is not None and previous.status != TimelineStatus.SUPERSEDED.value:
                # Parsed before superseding, purely to compare shots against
                # `timeline` below - the status mutation two lines down
                # doesn't affect any field carry-forward looks at.
                previous_timeline = Timeline.model_validate(previous.document)

                previous_document = dict(previous.document)
                previous_document["status"] = TimelineStatus.SUPERSEDED.value
                previous.document = previous_document
                previous.status = TimelineStatus.SUPERSEDED.value

                await self._carry_forward_bindings(project_id, previous_timeline, timeline)

        await self._repo.insert(
            project_id=project_id,
            version=timeline.version,
            parent_version=timeline.parent_version,
            produced_by=timeline.produced_by.value,
            status=timeline.status.value,
            document=timeline.model_dump(mode="json"),
        )

        project = await self._session.get(ProjectModel, project_id)
        if project is not None:
            project.active_timeline_version = timeline.version

        await self._session.commit()

    async def _carry_forward_bindings(
        self, project_id: uuid.UUID, previous_timeline: Timeline, new_timeline: Timeline
    ) -> None:
        """A11/A20 (M6.5) - see this module's docstring for why this lives
        here rather than as an opt-in helper. Per-shot, never all-or-
        nothing: a binding carries forward only when its `shot_id` still
        exists in `new_timeline` AND that shot's `prompt`/`asset_plan` are
        unchanged from `previous_timeline`. Narration changes only
        durations, so in that case every binding carries; a re-plan can
        change a shot's `prompt`, and carrying a binding across that
        change would silently serve an asset acquired for a question no
        longer being asked."""
        binding_repo = ShotBindingRepository(self._session)
        previous_bindings = await binding_repo.list_for_version(
            project_id, previous_timeline.version
        )
        if not previous_bindings:
            return  # nothing resolved yet at the previous version - nothing to carry

        previous_shots = {shot.id: shot for shot in previous_timeline.all_shots()}
        new_shots = {shot.id: shot for shot in new_timeline.all_shots()}

        for binding in previous_bindings:
            previous_shot = previous_shots.get(binding.shot_id)
            new_shot = new_shots.get(binding.shot_id)
            if previous_shot is None or new_shot is None:
                continue  # shot doesn't exist on one side - nothing to carry
            if (
                previous_shot.prompt != new_shot.prompt
                or previous_shot.asset_plan != new_shot.asset_plan
            ):
                continue  # acquisition-relevant fields changed - must re-resolve
            await binding_repo.carry_forward(binding, new_timeline_version=new_timeline.version)
