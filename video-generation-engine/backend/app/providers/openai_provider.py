"""OpenAI planning provider (ADR-003, M5). The only file in this codebase
that imports the `openai` package - every planner depends on
`PlanningLLMProvider` (app/providers/base.py), never on this class or the
SDK directly.

Structured output is forced via `response_format=<PydanticModel>`
(strict JSON-schema mode) rather than asking nicely in the prompt and
hoping - implementation guide, Phase M5 advice.
"""

import base64
from typing import Any, TypeVar

from openai import (
    APIConnectionError,
    APITimeoutError,
    AsyncOpenAI,
    BadRequestError,
    InternalServerError,
    OpenAIError,
    RateLimitError,
)
from openai.types.chat import (
    ChatCompletionContentPartImageParam,
    ChatCompletionContentPartTextParam,
    ChatCompletionMessageParam,
    ChatCompletionSystemMessageParam,
    ChatCompletionUserMessageParam,
)
from pydantic import BaseModel

from app.core.config import settings
from app.core.errors import PermanentError, TransientError
from app.core.logging import get_logger
from app.providers.base import ConstraintCheckRequest, ConstraintVerdict, StructuredCompletion

logger = get_logger(__name__)

ResponseModelT = TypeVar("ResponseModelT", bound=BaseModel)

_TRANSIENT_ERRORS = (RateLimitError, APITimeoutError, APIConnectionError, InternalServerError)

# Model ids observed to reject a custom `temperature` (see the fallback in
# `structured_complete`). Learned at runtime from OpenAI's own error rather
# than hardcoded, so it stays correct when the configured model changes -
# but remembered, so the doomed first attempt is paid ONCE per process
# instead of on every single planner call. Without this, a 5-scene script
# costs ~11 wasted round-trips and doubles planning latency.
_MODELS_REJECTING_TEMPERATURE: set[str] = set()


class OpenAIPlanningProvider:
    name = "openai"

    def __init__(self, client: AsyncOpenAI | None = None) -> None:
        self._client = client or AsyncOpenAI(
            api_key=settings.openai_api_key, organization=settings.openai_org_id
        )

    async def _parse(
        self,
        *,
        messages: list[dict[str, str]],
        response_model: type[ResponseModelT],
        seed: int | None,
        temperature: float | None,
    ) -> Any:
        kwargs: dict[str, Any] = {
            "model": settings.openai_planning_model,
            "seed": seed,
            "messages": messages,
            "response_format": response_model,
        }
        if temperature is not None:
            kwargs["temperature"] = temperature
        return await self._client.chat.completions.parse(**kwargs)

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
        model = settings.openai_planning_model
        # Skip the doomed attempt entirely once this model has already told
        # us it won't take a custom temperature.
        temperature = (
            None if model in _MODELS_REJECTING_TEMPERATURE else settings.openai_temperature
        )
        try:
            try:
                completion = await self._parse(
                    messages=messages,
                    response_model=response_model,
                    seed=seed,
                    temperature=temperature,
                )
            except BadRequestError as exc:
                # Reasoning-tier models (o-series, gpt-5.x) reject any
                # temperature other than their fixed default and report it
                # via this exact param/code pair - fall back to the
                # model's default rather than hardcoding a model allowlist
                # that will be stale the next time the configured model
                # changes. Remembering the answer keeps that discovery to
                # one wasted request per process rather than one per call.
                if temperature is not None and exc.param == "temperature":
                    _MODELS_REJECTING_TEMPERATURE.add(model)
                    logger.info(
                        "openai.temperature_unsupported_falling_back_to_default",
                        extra={"model": model},
                    )
                    completion = await self._parse(
                        messages=messages,
                        response_model=response_model,
                        seed=seed,
                        temperature=None,
                    )
                else:
                    raise PermanentError(f"openai error: {exc}") from exc
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

    async def check_constraints(self, request: ConstraintCheckRequest) -> StructuredCompletion:
        """M6.5, A12 - `VisionConstraintProvider`. Same structured-output
        call shape as `structured_complete` above, but with an image
        content block attached; a separate, smaller model
        (`settings.openai_vision_model`) rather than the planning model,
        since vision support isn't guaranteed on every model choice and
        this is a mechanical check, not creative judgement."""
        image_b64 = base64.b64encode(request.image).decode("ascii")
        data_url = f"data:{request.image_content_type};base64,{image_b64}"
        constraints_text = "\n".join(f"- {c}" for c in request.constraints)

        system_message: ChatCompletionSystemMessageParam = {
            "role": "system",
            "content": (
                "You check a generated image against a fixed list of hard "
                "creative constraints. Flag a violation only if it is "
                "genuinely visible in the image - do not invent one, and do "
                "not flag a constraint the image plainly satisfies."
            ),
        }
        text_part: ChatCompletionContentPartTextParam = {
            "type": "text",
            "text": (
                f"Shot prompt this image was generated from: {request.shot_prompt}\n\n"
                f"Constraints this image must not violate:\n{constraints_text}"
            ),
        }
        image_part: ChatCompletionContentPartImageParam = {
            "type": "image_url",
            "image_url": {"url": data_url},
        }
        user_message: ChatCompletionUserMessageParam = {
            "role": "user",
            "content": [text_part, image_part],
        }
        messages: list[ChatCompletionMessageParam] = [system_message, user_message]
        try:
            completion = await self._client.chat.completions.parse(
                model=settings.openai_vision_model,
                messages=messages,
                response_format=ConstraintVerdict,
            )
        except _TRANSIENT_ERRORS as exc:
            raise TransientError(f"openai vision check transient error: {exc}") from exc
        except OpenAIError as exc:
            raise PermanentError(f"openai vision check error: {exc}") from exc

        choice = completion.choices[0]
        if choice.message.refusal:
            raise PermanentError(f"openai refused the vision check: {choice.message.refusal}")
        parsed = choice.message.parsed
        if parsed is None:
            raise PermanentError("openai did not return a parseable constraint verdict")

        usage = completion.usage
        # `request` deliberately omits the base64 image data URI - it can be
        # megabytes, and the point of the audit row (like every other
        # `llm_call`) is "what was asked and what came back", not a second
        # copy of the image bytes themselves. (Not "it's already on disk" -
        # a REJECTED attempt's bytes are deliberately never written anywhere;
        # this is purely about not bloating the `llm_call` audit row.)
        return StructuredCompletion(
            parsed=parsed,
            model=completion.model,
            request={
                "model": settings.openai_vision_model,
                "shot_prompt": request.shot_prompt,
                "constraints": request.constraints,
            },
            response=choice.message.model_dump(mode="json"),
            input_tokens=usage.prompt_tokens if usage else None,
            output_tokens=usage.completion_tokens if usage else None,
        )
