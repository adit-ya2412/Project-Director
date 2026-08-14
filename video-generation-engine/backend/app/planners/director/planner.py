"""Director agent (M5, first link in the Director -> Scene Planner ->
Shot Planner -> Asset Planner chain). Sets creative_context and
music_plan for the whole project - nothing else. See
app/prompts/director/v1.md for the prompt specification."""

import uuid

from app.planners.director.schemas import DirectorOutput
from app.planners.repair import run_structured_with_repair
from app.prompts.loader import load_prompt
from app.providers.base import PlanningLLMProvider
from app.repositories.llm_call_repository import LlmCallRepository
from app.schemas.timeline import CreativeContext, MusicPlan

AGENT = "director"
PROMPT_VERSION = "v1"


def _validate(output: DirectorOutput) -> list[str]:
    violations: list[str] = []
    ctx = output.creative_context
    for field_name in ("tone", "visual_style", "historical_period", "audience", "camera_language"):
        if not getattr(ctx, field_name).strip():
            violations.append(f"creative_context.{field_name} must not be empty")
    if not ctx.colour_palette:
        violations.append("creative_context.colour_palette must not be empty")

    plan = output.music_plan
    if not plan.mood.strip():
        violations.append("music_plan.mood must not be empty")
    if not plan.tempo.strip():
        violations.append("music_plan.tempo must not be empty")
    if not plan.search_terms:
        violations.append("music_plan.search_terms must not be empty")

    return violations


class DirectorPlanner:
    name = AGENT

    def __init__(self, provider: PlanningLLMProvider, llm_call_repo: LlmCallRepository) -> None:
        self._provider = provider
        self._llm_call_repo = llm_call_repo

    async def plan(self, *, project_id: str, script: str) -> tuple[CreativeContext, MusicPlan]:
        system_prompt = load_prompt(AGENT, PROMPT_VERSION)
        output = await run_structured_with_repair(
            provider=self._provider,
            llm_call_repo=self._llm_call_repo,
            project_id=uuid.UUID(project_id),
            agent=AGENT,
            prompt_version=PROMPT_VERSION,
            system_prompt=system_prompt,
            user_content=f"Script:\n\n{script}",
            response_model=DirectorOutput,
            validate=_validate,
        )
        creative_context = CreativeContext(**output.creative_context.model_dump())
        music_plan = MusicPlan(**output.music_plan.model_dump())
        return creative_context, music_plan
