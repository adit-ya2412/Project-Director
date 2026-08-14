"""Narration persistence. `content_hash` dedup is deliberately GLOBAL, not
per-project - mirrors `GeneratedClipRepository.get_by_prompt_hash` (ladder
rung 0): the same scene text narrated with the same voice/model/
output_format is the same paid call no matter which project asks for it.

Unlike `GeneratedClip`, ElevenLabs' `/with-timestamps` endpoint is
request-response, not submit-and-poll (fal.ai's queue is the only
asynchronous provider in this system) - so there is no pending/in-flight
state to manage here, just a lookup before the call and an insert after.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.narration import NarrationModel


class NarrationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_content_hash(self, content_hash: str) -> NarrationModel | None:
        result = await self._session.execute(
            select(NarrationModel).where(NarrationModel.content_hash == content_hash)
        )
        return result.scalar_one_or_none()

    async def total_cost_cents_for_project(self, project_id: uuid.UUID) -> int:
        """Mirrors `GeneratedClipRepository.total_cost_cents_for_project` -
        narration spend counts against the same per-project budget cap
        (M8 open decision: "does TTS count against the budget cap?" -
        yes, see `app/assets/cost.total_project_spend_cents`)."""
        result = await self._session.execute(
            select(func.coalesce(func.sum(NarrationModel.cost_cents), 0)).where(
                NarrationModel.project_id == project_id
            )
        )
        return int(result.scalar_one())

    async def insert(
        self,
        *,
        project_id: uuid.UUID,
        scene_id: str,
        provider: str,
        voice_id: str,
        model_id: str,
        output_format: str,
        text: str,
        content_hash: str,
        local_path: str,
        alignment: dict,
        character_count: int,
        cost_cents: int,
    ) -> NarrationModel:
        model = NarrationModel(
            project_id=project_id,
            scene_id=scene_id,
            provider=provider,
            voice_id=voice_id,
            model_id=model_id,
            output_format=output_format,
            text=text,
            content_hash=content_hash,
            local_path=local_path,
            alignment=alignment,
            character_count=character_count,
            cost_cents=cost_cents,
        )
        self._session.add(model)
        await self._session.flush()
        return model
