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

    async def get_latest_completed_for_output(
        self,
        project_id: uuid.UUID,
        *,
        output_path: str,
        is_draft: bool = False,
    ) -> RenderModel | None:
        """Most recent completed render for this project at ``output_path``.

        Lookup is by the project's own output path (e.g. ``final.mp4``) so
        a draft row cannot satisfy a final check, and vice versa (K16.8).
        """
        result = await self._session.execute(
            select(RenderModel)
            .where(
                RenderModel.project_id == project_id,
                RenderModel.output_path == output_path,
                RenderModel.status == "completed",
                RenderModel.is_draft.is_(is_draft),
            )
            .order_by(RenderModel.created_at.desc())
            .limit(1)
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
