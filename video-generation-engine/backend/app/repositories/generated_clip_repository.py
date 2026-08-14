"""GeneratedClip persistence. `prompt_hash` dedup is deliberately GLOBAL,
not per-project (unlike Asset) - identical generations are reused across
projects too. This is ladder rung 0 (implementation guide, Phase M7):
the single biggest cost saving in the system."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.generated_clip import GeneratedClipModel


class GeneratedClipRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_prompt_hash(self, prompt_hash: str) -> GeneratedClipModel | None:
        result = await self._session.execute(
            select(GeneratedClipModel).where(GeneratedClipModel.prompt_hash == prompt_hash)
        )
        return result.scalar_one_or_none()

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
        )
        self._session.add(model)
        await self._session.flush()
        return model
