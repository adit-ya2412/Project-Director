"""OpenAI planning provider (ADR-003, M5). The only file in this codebase
that imports the `openai` package - every planner depends on
`PlanningLLMProvider` (app/providers/base.py), never on this class or the
SDK directly.

Structured output is forced via `response_format=<PydanticModel>`
(strict JSON-schema mode) rather than asking nicely in the prompt and
hoping - implementation guide, Phase M5 advice.
"""

from typing import TypeVar

from openai import (
    APIConnectionError,
    APITimeoutError,
    AsyncOpenAI,
    InternalServerError,
    OpenAIError,
    RateLimitError,
)
from pydantic import BaseModel

from app.core.config import settings
from app.core.errors import PermanentError, TransientError
from app.providers.base import StructuredCompletion

ResponseModelT = TypeVar("ResponseModelT", bound=BaseModel)

_TRANSIENT_ERRORS = (RateLimitError, APITimeoutError, APIConnectionError, InternalServerError)


class OpenAIPlanningProvider:
    name = "openai"

    def __init__(self, client: AsyncOpenAI | None = None) -> None:
        self._client = client or AsyncOpenAI(
            api_key=settings.openai_api_key, organization=settings.openai_org_id
        )

    async def structured_complete(
        self,
        *,
        system_prompt: str,
        user_content: str,
        response_model: type[ResponseModelT],
        seed: int | None = None,
    ) -> StructuredCompletion:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]
        try:
            completion = await self._client.chat.completions.parse(
                model=settings.openai_planning_model,
                temperature=settings.openai_temperature,
                seed=seed,
                messages=messages,  # type: ignore[arg-type]
                response_format=response_model,
            )
        except _TRANSIENT_ERRORS as exc:
            raise TransientError(f"openai transient error: {exc}") from exc
        except OpenAIError as exc:
            raise PermanentError(f"openai error: {exc}") from exc

        choice = completion.choices[0]
        if choice.message.refusal:
            raise PermanentError(f"openai refused the request: {choice.message.refusal}")
        parsed = choice.message.parsed
        if parsed is None:
            raise PermanentError("openai did not return parseable structured output")

        usage = completion.usage
        return StructuredCompletion(
            parsed=parsed,
            model=completion.model,
            request={"model": settings.openai_planning_model, "messages": messages},
            response=choice.message.model_dump(mode="json"),
            input_tokens=usage.prompt_tokens if usage else None,
            output_tokens=usage.completion_tokens if usage else None,
        )
