"""Shared "call once, validate, repair once" loop used by every planning
agent (implementation guide, Phase M5 advice: "allow exactly one repair
round-trip, then fail permanently. Unbounded repair loops burn money
silently.").

Every attempt - including a failed first attempt that triggers a repair -
is recorded as its own `llm_call` row, regardless of outcome.
"""

import uuid
from collections.abc import Callable
from typing import TypeVar

from pydantic import BaseModel

from app.core.config import settings
from app.core.errors import PermanentError
from app.providers.base import PlanningLLMProvider
from app.repositories.llm_call_repository import LlmCallRepository

OutputT = TypeVar("OutputT", bound=BaseModel)


async def run_structured_with_repair(
    *,
    provider: PlanningLLMProvider,
    llm_call_repo: LlmCallRepository,
    project_id: uuid.UUID,
    agent: str,
    prompt_version: str,
    system_prompt: str,
    user_content: str,
    response_model: type[OutputT],
    validate: Callable[[OutputT], list[str]],
    seed: int | None = None,
) -> OutputT:
    attempt_user_content = user_content
    attempts = 0
    max_attempts = 1 + settings.planner_max_repair_attempts

    while True:
        attempts += 1
        completion = await provider.structured_complete(
            system_prompt=system_prompt,
            user_content=attempt_user_content,
            response_model=response_model,
            seed=seed,
        )
        await llm_call_repo.insert(
            project_id=project_id,
            agent=agent,
            prompt_version=prompt_version,
            model=completion.model,
            request=completion.request,
            response=completion.response,
            input_tokens=completion.input_tokens,
            output_tokens=completion.output_tokens,
        )

        parsed: OutputT = completion.parsed  # type: ignore[assignment]
        violations = validate(parsed)
        if not violations:
            return parsed

        if attempts >= max_attempts:
            raise PermanentError(
                f"{agent} output failed validation after {attempts} attempt(s): {violations}"
            )

        attempt_user_content = (
            f"{user_content}\n\n"
            "Your previous response violated these constraints. Correct them and "
            "respond again with a full, corrected output:\n"
            + "\n".join(f"- {v}" for v in violations)
        )
