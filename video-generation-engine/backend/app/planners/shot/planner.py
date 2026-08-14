"""Shot Planner agent (M5, third link in the chain). Fills `shots` for
every scene - one LLM call per scene, so the narration-span and duration-
sum constraints stay scoped to something the model can actually reason
about. See app/prompts/shot_planner/v1.md for the prompt specification.

A crash mid-loop (after scene 3's shots landed, before scene 4's) is not
separately resumable within this call - `GenerateTimelineStep` only
checkpoints once, via one `append_version`, after every scene in this
loop has succeeded. A retry re-plans every scene. This is a deliberate
scope boundary (see the Implementation Guide M5 section): step-level
resumability, not sub-call-level.
"""

import uuid

from app.core.errors import PermanentError
from app.planners.repair import run_structured_with_repair
from app.planners.shot.schemas import ShotPlannerOutput, ShotPlanOutput
from app.prompts.loader import load_prompt
from app.providers.base import PlanningLLMProvider
from app.repositories.llm_call_repository import LlmCallRepository
from app.schemas.timeline import Camera, CreativeContext, Scene, Shot, Transition


def _build_user_content(scene: Scene, creative_context: CreativeContext) -> str:
    return (
        f"Scene: {scene.title}\n"
        f"Narrative purpose: {scene.narrative_purpose}\n"
        f"Emotion: {scene.emotion}\n"
        f"Target scene duration_s: {scene.duration_s}\n"
        f"Narration text for this scene (index shots against THIS exact string):\n"
        f"{scene.narration_text}\n\n"
        "Director's creative context:\n"
        f"- historical_period: {creative_context.historical_period}\n"
        f"- visual_style: {creative_context.visual_style}\n"
        f"- camera_language: {creative_context.camera_language}\n"
    )


def _make_validator(scene: Scene, min_shot_duration_s: float, max_shot_duration_s: float):
    narration_len = len(scene.narration_text)

    def _validate(output: ShotPlannerOutput) -> list[str]:
        violations: list[str] = []
        shots = output.shots

        if not shots:
            violations.append("shots must not be empty")
            return violations

        ids = [s.id for s in shots]
        if len(ids) != len(set(ids)):
            violations.append("shot ids must be unique within the scene")

        expected_order = list(range(len(shots)))
        if [s.order for s in shots] != expected_order:
            violations.append(f"shot order fields must be exactly {expected_order}, in list order")

        cursor = 0
        for s in shots:
            if s.narration_start != cursor:
                violations.append(
                    f"shot {s.id} narration_start ({s.narration_start}) must equal "
                    f"{cursor} - spans must be contiguous with no gaps or overlaps"
                )
            if s.narration_end <= s.narration_start:
                violations.append(f"shot {s.id} narration_end must be greater than narration_start")
            cursor = s.narration_end
        if cursor != narration_len:
            violations.append(
                f"the last shot's narration_end ({cursor}) must equal the scene narration "
                f"length ({narration_len}) - every character must be covered"
            )

        for s in shots:
            if not (min_shot_duration_s <= s.duration_s <= max_shot_duration_s):
                violations.append(
                    f"shot {s.id} duration_s={s.duration_s} outside "
                    f"[{min_shot_duration_s}, {max_shot_duration_s}]"
                )

        total = sum(s.duration_s for s in shots)
        tolerance = max(1.0, 0.2 * scene.duration_s)
        if abs(total - scene.duration_s) > tolerance:
            violations.append(
                f"shot durations sum to {total:.1f}s, expected close to the scene's "
                f"{scene.duration_s}s (tolerance {tolerance:.1f}s)"
            )

        return violations

    return _validate


def _to_domain_shot(s: ShotPlanOutput) -> Shot:
    return Shot(
        id=s.id,
        order=s.order,
        intent=s.intent,
        intent_text=s.intent_text,
        narration_span=(s.narration_start, s.narration_end),
        duration_s=s.duration_s,
        framing=s.framing,
        camera=Camera(
            movement=s.camera.movement, direction=s.camera.direction, intensity=s.camera.intensity
        ),
        transition_out=Transition(
            type=s.transition_out.type, duration_s=s.transition_out.duration_s
        ),
        prompt=s.prompt,
        asset_plan=None,
    )


class ShotPlanner:
    name = "shot_planner"
    _PROMPT_VERSION = "v1"

    def __init__(self, provider: PlanningLLMProvider, llm_call_repo: LlmCallRepository) -> None:
        self._provider = provider
        self._llm_call_repo = llm_call_repo

    async def plan(
        self,
        *,
        project_id: str,
        scenes: list[Scene],
        creative_context: CreativeContext,
        min_shot_duration_s: float,
        max_shot_duration_s: float,
        max_shots_per_project: int,
    ) -> list[Scene]:
        system_prompt = load_prompt(self.name, self._PROMPT_VERSION)
        planned_scenes: list[Scene] = []
        total_shots = 0

        for scene in scenes:
            output = await run_structured_with_repair(
                provider=self._provider,
                llm_call_repo=self._llm_call_repo,
                project_id=uuid.UUID(project_id),
                agent=self.name,
                prompt_version=self._PROMPT_VERSION,
                system_prompt=system_prompt,
                user_content=_build_user_content(scene, creative_context),
                response_model=ShotPlannerOutput,
                validate=_make_validator(scene, min_shot_duration_s, max_shot_duration_s),
            )
            total_shots += len(output.shots)
            if total_shots > max_shots_per_project:
                raise PermanentError(
                    f"shot planner exceeded max_shots_per_project ({max_shots_per_project}) "
                    f"after scene {scene.id} - {total_shots} shots planned so far"
                )
            planned_scenes.append(
                scene.model_copy(update={"shots": [_to_domain_shot(s) for s in output.shots]})
            )

        return planned_scenes
