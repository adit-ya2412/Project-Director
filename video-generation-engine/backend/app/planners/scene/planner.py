"""Scene Planner agent (M5, second link in the chain). Breaks the full
script into an ordered list of scenes - narrative structure only, no
shots yet. See app/prompts/scene_planner/v1.md for the prompt
specification."""

import re
import uuid

from app.planners.repair import run_structured_with_repair
from app.planners.scene.schemas import ScenePlannerOutput
from app.prompts.loader import load_prompt
from app.providers.base import PlanningLLMProvider
from app.repositories.llm_call_repository import LlmCallRepository
from app.schemas.timeline import CreativeContext, Scene

AGENT = "scene_planner"
PROMPT_VERSION = "v1"

_WHITESPACE_RE = re.compile(r"\s+")


def _normalise(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", text).strip().lower()


def _build_user_content(script: str, creative_context: CreativeContext, max_scenes: int) -> str:
    return (
        f"Script:\n\n{script}\n\n"
        "Director's creative context:\n"
        f"- tone: {creative_context.tone}\n"
        f"- visual_style: {creative_context.visual_style}\n"
        f"- historical_period: {creative_context.historical_period}\n"
        f"- audience: {creative_context.audience}\n\n"
        f"Constraints: produce at most {max_scenes} scenes."
    )


def _make_validator(script: str, max_scenes: int, max_video_duration_s: float):
    expected = _normalise(script)

    def _validate(output: ScenePlannerOutput) -> list[str]:
        violations: list[str] = []
        scenes = output.scenes

        if not scenes:
            violations.append("scenes must not be empty")
            return violations
        if len(scenes) > max_scenes:
            violations.append(f"{len(scenes)} scenes exceeds the maximum of {max_scenes}")

        ids = [s.id for s in scenes]
        if len(ids) != len(set(ids)):
            violations.append("scene ids must be unique")

        expected_order = list(range(len(scenes)))
        if [s.order for s in scenes] != expected_order:
            violations.append(f"scene order fields must be exactly {expected_order}, in list order")

        total_duration = sum(s.duration_s for s in scenes)
        if total_duration > max_video_duration_s:
            violations.append(
                f"total scene duration {total_duration:.1f}s exceeds max_video_duration_s "
                f"{max_video_duration_s}"
            )
        for s in scenes:
            if s.duration_s <= 0:
                violations.append(f"scene {s.id} duration_s must be positive")

        joined = _normalise(" ".join(s.narration_text for s in scenes))
        if joined != expected:
            violations.append(
                "concatenating every scene's narration_text (in order) must reproduce the "
                "script's narration content exactly - no words dropped, added, or reordered"
            )

        return violations

    return _validate


class ScenePlanner:
    name = AGENT

    def __init__(self, provider: PlanningLLMProvider, llm_call_repo: LlmCallRepository) -> None:
        self._provider = provider
        self._llm_call_repo = llm_call_repo

    async def plan(
        self,
        *,
        project_id: str,
        script: str,
        creative_context: CreativeContext,
        max_scenes: int,
        max_video_duration_s: float,
    ) -> list[Scene]:
        system_prompt = load_prompt(AGENT, PROMPT_VERSION)
        output = await run_structured_with_repair(
            provider=self._provider,
            llm_call_repo=self._llm_call_repo,
            project_id=uuid.UUID(project_id),
            agent=AGENT,
            prompt_version=PROMPT_VERSION,
            system_prompt=system_prompt,
            user_content=_build_user_content(script, creative_context, max_scenes),
            response_model=ScenePlannerOutput,
            validate=_make_validator(script, max_scenes, max_video_duration_s),
        )
        return [
            Scene(
                id=s.id,
                order=s.order,
                title=s.title,
                summary=s.summary,
                emotion=s.emotion,
                narrative_purpose=s.narrative_purpose,
                narration_text=s.narration_text,
                duration_s=s.duration_s,
                shots=[],
            )
            for s in output.scenes
        ]
