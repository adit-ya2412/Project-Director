"""ShotBinding persistence — the media generation work queue.

`list_for_version(...)` filtered to `state == "pending"` (or anything
non-terminal) is literally the work list M7's media generation loop reads
from.
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
