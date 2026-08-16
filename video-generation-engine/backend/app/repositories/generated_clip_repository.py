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

    async def count_for_shot(self, project_id: uuid.UUID, shot_id: str) -> int:
        """How many `GeneratedClip` rows already exist for this shot in
        this project - regardless of status. Used (M9, Task 3) to derive
        a per-attempt seed for `/shots/{id}/generate`: the Nth explicit
        generation click for a shot must vary its seed from the (N-1)th,
        or a human clicking "generate" again on an unchanged prompt would
        just hit the SAME `prompt_hash` (project seed folded in
        unchanged) and silently get the identical image back for free.
        Deliberately COUNTS rather than looks up a max attempt index -
        `status` (`"completed"`/`"rejected"`/`"failed"`) doesn't matter
        here the way it does for the constraint-retry cache lookup
        elsewhere: every row, of any status, represents an attempt
        already made against fal.ai, and the next attempt must not reuse
        any of their seeds."""
        result = await self._session.execute(
            select(func.count(GeneratedClipModel.id)).where(
                GeneratedClipModel.project_id == project_id,
                GeneratedClipModel.shot_id == shot_id,
            )
        )
        return int(result.scalar_one())

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
        local_path: str | None,
        cost_cents: int,
        status: str = "completed",
        error: str | None = None,
        violated_constraint: str | None = None,
    ) -> GeneratedClipModel:
        """`status`/`error`/`violated_constraint` default to the original
        "synchronous success" shape every existing caller relies on. M6.5
        (A12/A13) adds a third status, `"rejected"`: a generation that
        violated a Director constraint - never shipped, `local_path`
        stays `None` since nothing was ever written to disk, but still
        billed here (`cost_cents`), so a rejected attempt still counts
        against the project budget cap. The existing cache-hit check
        elsewhere (`if cached is not None and cached.status ==
        "completed"`) already excludes anything not `"completed"` - a
        rejected row is never served back out as if it were a valid,
        reusable clip. `violated_constraint` is the exact constraint text
        (not embedded in `error`'s free-form string) - a resumed run that
        finds its own prior "rejected" row for this exact attempt needs
        it back in a form it can rebuild the next attempt's prompt from,
        without regenerating (and re-billing) an attempt already known to
        fail."""
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
            status=status,
            error=error,
            violated_constraint=violated_constraint,
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
