"""Render persistence (M8 step 6, I5). `fingerprint` dedup is GLOBAL, not
per-project - mirrors `GeneratedClipRepository.get_by_prompt_hash` (ladder
rung 0) and `NarrationRepository.get_by_content_hash`: the same exact
render (Timeline content, assets, narration, music, settings, ffmpeg
version, all byte-identical) is the same file no matter which project's
run happens to reproduce it, and re-encoding it a second time is pure
waste - I5 is what proves that reuse is safe, not just fast.
"""

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.render import RenderModel


class RenderRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_completed_by_fingerprint(self, fingerprint: str) -> RenderModel | None:
        result = await self._session.execute(
            select(RenderModel).where(
                RenderModel.fingerprint == fingerprint,
                RenderModel.status == "completed",
            )
        )
        return result.scalar_one_or_none()

    async def list_completed_drafts_older_than(
        self, cutoff: datetime
    ) -> list[RenderModel]:
        """Completed draft rows created before `cutoff` (§19.9)."""
        result = await self._session.execute(
            select(RenderModel).where(
                RenderModel.status == "completed",
                RenderModel.is_draft.is_(True),
                RenderModel.created_at < cutoff,
            )
        )
        return list(result.scalars().all())

    async def delete(self, model: RenderModel) -> None:
        await self._session.delete(model)
        await self._session.flush()

    async def insert_completed(
        self,
        *,
        project_id: uuid.UUID,
        output_path: str,
        fingerprint: str,
        settings: dict,
        width: int,
        height: int,
        fps: int,
        duration_s: float,
        is_draft: bool = False,
    ) -> RenderModel:
        model = RenderModel(
            project_id=project_id,
            status="completed",
            output_path=output_path,
            fingerprint=fingerprint,
            settings=settings,
            width=width,
            height=height,
            fps=fps,
            duration_s=duration_s,
            is_draft=is_draft,
        )
        self._session.add(model)
        await self._session.flush()
        return model
