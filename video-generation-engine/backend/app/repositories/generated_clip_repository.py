"""GeneratedClip persistence. `prompt_hash` dedup is deliberately GLOBAL,
not per-project (unlike Asset) - identical generations are reused across
projects too. This is ladder rung 0 (implementation guide, Phase M7):
the single biggest cost saving in the system.

`insert_pending`/`mark_completed`/`mark_failed` exist for fal's
submit-and-poll shape: a row is persisted the instant a paid job is
submitted (before anything else - implementation guide, Phase M7
advice), so a crash between submit and persist never orphans a job
you've already paid for. `insert` remains for synchronous (fake/dry-run)
generation, which never has a pending state."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.generated_clip import GeneratedClipModel

IN_FLIGHT_STATUSES = frozenset({"submitted", "in_progress"})


class GeneratedClipRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_prompt_hash(self, prompt_hash: str) -> GeneratedClipModel | None:
        result = await self._session.execute(
            select(GeneratedClipModel).where(GeneratedClipModel.prompt_hash == prompt_hash)
        )
        return result.scalar_one_or_none()

    async def get_in_flight_for_shot(
        self, project_id: uuid.UUID, shot_id: str
    ) -> GeneratedClipModel | None:
        """The job most recently submitted for this shot, if it hasn't
        resolved yet - the resume path for a crash between submit and
        completion."""
        result = await self._session.execute(
            select(GeneratedClipModel)
            .where(
                GeneratedClipModel.project_id == project_id,
                GeneratedClipModel.shot_id == shot_id,
                GeneratedClipModel.status.in_(IN_FLIGHT_STATUSES),
            )
            .order_by(GeneratedClipModel.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def total_cost_cents_for_project(self, project_id: uuid.UUID) -> int:
        result = await self._session.execute(
            select(func.coalesce(func.sum(GeneratedClipModel.cost_cents), 0)).where(
                GeneratedClipModel.project_id == project_id
            )
        )
        return int(result.scalar_one())

    async def insert(
        self,
        *,
        project_id,
        shot_id: str,
        provider: str,
        model_id: str,
        prompt: str,
        prompt_hash: str,
        duration_s: float | None,
        local_path: str,
        cost_cents: int,
    ) -> GeneratedClipModel:
        model = GeneratedClipModel(
            project_id=project_id,
            shot_id=shot_id,
            provider=provider,
            model_id=model_id,
            prompt=prompt,
            prompt_hash=prompt_hash,
            duration_s=duration_s,
            local_path=local_path,
            cost_cents=cost_cents,
            status="completed",
        )
        self._session.add(model)
        await self._session.flush()
        return model

    async def insert_pending(
        self,
        *,
        project_id: uuid.UUID,
        shot_id: str,
        provider: str,
        model_id: str,
        prompt: str,
        prompt_hash: str,
        job_id: str,
        estimated_cost_cents: int,
    ) -> GeneratedClipModel:
        model = GeneratedClipModel(
            project_id=project_id,
            shot_id=shot_id,
            provider=provider,
            model_id=model_id,
            prompt=prompt,
            prompt_hash=prompt_hash,
            duration_s=None,
            local_path=None,
            cost_cents=estimated_cost_cents,
            job_id=job_id,
            status="submitted",
        )
        self._session.add(model)
        await self._session.flush()
        return model

    async def mark_in_progress(self, clip: GeneratedClipModel) -> None:
        clip.status = "in_progress"

    async def mark_completed(
        self,
        clip: GeneratedClipModel,
        *,
        local_path: str,
        duration_s: float | None,
        cost_cents: int,
    ) -> None:
        clip.local_path = local_path
        clip.duration_s = duration_s
        clip.cost_cents = cost_cents
        clip.status = "completed"

    async def mark_failed(self, clip: GeneratedClipModel, *, error: str) -> None:
        clip.status = "failed"
        clip.error = error
