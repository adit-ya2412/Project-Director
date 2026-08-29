"""LlmCall persistence - every planning exchange, real or repaired, is
recorded here (implementation guide, Phase M5 advice: "record every LLM
exchange"). This is what makes planning auditable and replayable."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.llm_call import LlmCallModel


class LlmCallRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def insert(
        self,
        *,
        project_id: uuid.UUID,
        agent: str,
        prompt_version: str | None,
        model: str,
        request: dict,
        response: dict,
        input_tokens: int | None,
        output_tokens: int | None,
        cost_cents: int | None = None,
        input_usd_per_1m: float | None = None,
        output_usd_per_1m: float | None = None,
    ) -> LlmCallModel:
        call = LlmCallModel(
            project_id=project_id,
            agent=agent,
            prompt_version=prompt_version,
            model=model,
            request=request,
            response=response,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_cents=cost_cents,
            input_usd_per_1m=input_usd_per_1m,
            output_usd_per_1m=output_usd_per_1m,
        )
        self._session.add(call)
        await self._session.flush()
        return call
