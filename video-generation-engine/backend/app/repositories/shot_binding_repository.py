"""ShotBinding persistence — the media generation work queue.

`list_for_version(...)` filtered to `state == "pending"` (or anything
non-terminal) is literally the work list M7's media generation loop reads
from.

`TERMINAL_STATES` means "nothing left to do for this shot, ever" -
deliberately excludes `awaiting_generation` (M6.5, A5/A21), which means
"the free search pass is done with this shot, but the paid generation
pass still has work to do." Each `ResolveAssetsStep` instance derives its
OWN pass-specific "done" set from this plus whether it is permitted to
generate - see that module.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.shot_binding import ShotBindingModel

TERMINAL_STATES = frozenset({"resolved", "generated", "failed", "skipped"})


class ShotBindingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(
        self, project_id: uuid.UUID, timeline_version: int, shot_id: str
    ) -> ShotBindingModel | None:
        result = await self._session.execute(
            select(ShotBindingModel).where(
                ShotBindingModel.project_id == project_id,
                ShotBindingModel.timeline_version == timeline_version,
                ShotBindingModel.shot_id == shot_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_for_version(
        self, project_id: uuid.UUID, timeline_version: int
    ) -> list[ShotBindingModel]:
        result = await self._session.execute(
            select(ShotBindingModel).where(
                ShotBindingModel.project_id == project_id,
                ShotBindingModel.timeline_version == timeline_version,
            )
        )
        return list(result.scalars().all())

    async def get_or_create_pending(
        self, project_id: uuid.UUID, timeline_version: int, shot_id: str
    ) -> ShotBindingModel:
        existing = await self.get(project_id, timeline_version, shot_id)
        if existing is not None:
            return existing
        binding = ShotBindingModel(
            project_id=project_id,
            timeline_version=timeline_version,
            shot_id=shot_id,
            state="pending",
        )
        self._session.add(binding)
        await self._session.flush()
        return binding

    async def carry_forward(
        self, binding: ShotBindingModel, *, new_timeline_version: int
    ) -> ShotBindingModel:
        """A11/A20 (M6.5): copies a binding's resolved execution state to
        a new timeline version - the old row is left exactly as it was
        (bindings are never deleted or mutated across a version boundary,
        same immutability spirit as the Timeline versions themselves).
        Called only from `TimelineService` (see its own docstring on
        why carry-forward lives there, not here) - this method itself
        doesn't decide WHETHER to carry a binding forward, only how."""
        carried = ShotBindingModel(
            project_id=binding.project_id,
            timeline_version=new_timeline_version,
            shot_id=binding.shot_id,
            state=binding.state,
            asset_id=binding.asset_id,
            clip_id=binding.clip_id,
            rung=binding.rung,
            attempts=binding.attempts,
            last_error=binding.last_error,
            cost_cents=binding.cost_cents,
        )
        self._session.add(carried)
        await self._session.flush()
        return carried
