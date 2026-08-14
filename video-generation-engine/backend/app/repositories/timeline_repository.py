"""Timeline version persistence — pure data access, no versioning policy.

The policy (deep-copy-before-transform, additive-only enforcement,
"append_version is the only writer") lives in `app.timeline.service`.
This repository just reads and inserts rows; it never decides whether a
write is *allowed*.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.timeline_version import TimelineVersionModel


class TimelineVersionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_latest(self, project_id: uuid.UUID) -> TimelineVersionModel | None:
        result = await self._session.execute(
            select(TimelineVersionModel)
            .where(TimelineVersionModel.project_id == project_id)
            .order_by(TimelineVersionModel.version.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_by_version(
        self, project_id: uuid.UUID, version: int
    ) -> TimelineVersionModel | None:
        result = await self._session.execute(
            select(TimelineVersionModel).where(
                TimelineVersionModel.project_id == project_id,
                TimelineVersionModel.version == version,
            )
        )
        return result.scalar_one_or_none()

    async def insert(
        self,
        *,
        project_id: uuid.UUID,
        version: int,
        parent_version: int | None,
        produced_by: str,
        status: str,
        document: dict,
    ) -> TimelineVersionModel:
        model = TimelineVersionModel(
            project_id=project_id,
            version=version,
            parent_version=parent_version,
            produced_by=produced_by,
            status=status,
            document=document,
        )
        self._session.add(model)
        await self._session.flush()
        return model
