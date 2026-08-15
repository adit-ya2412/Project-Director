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
from app.core.logging import get_logger
from app.planners.repair import run_structured_with_repair
from app.planners.shot.schemas import ShotPlannerOutput, ShotPlanOutput
from app.prompts.loader import load_prompt
from app.providers.base import PlanningLLMProvider
from app.repositories.llm_call_repository import LlmCallRepository
from app.schemas.timeline import Camera, CreativeContext, Scene, Shot, Transition

logger = get_logger(__name__)

# A model that is a handful of characters off the scene's true boundary is
# being imprecise about a trailing space or a bit of punctuation (the real
# case that motivated this: 144 vs 140, a trailing space before the
# scene's final "hi. "). A model that is off by dozens of characters
# instead genuinely misunderstood where the scene starts or ends - still
# safe to snap (the boundary is a structural fact either way, not a
# creative one), but worth a human noticing in the logs. 10 characters
# sits strictly between those two observed cases.
_LARGE_SNAP_THRESHOLD_CHARS = 10


def _snap_narration_boundaries(
    shots: list[ShotPlanOutput], narration_len: int, *, scene_id: str
) -> None:
    """The first shot's `narration_start` is always 0 and the last shot's
    `narration_end` is always `narration_len` - these are structural facts
    about the scene text the caller already knows, not creative decisions
    the model is being asked to make, so they are corrected here rather
    than validated and rejected. Demanding the model reproduce them
    exactly and hard-failing the whole project over a four-character miss
    is the same mistake the cross-scene shot-id collision already taught
    once (implementation guide, M5 notes) - something deterministic was
    being delegated to a language model.

    Deliberately narrow: only the two OUTER boundaries are touched.
    Internal gaps and overlaps between consecutive shots are genuine
    structural errors and are still caught by the validation loop that
    runs right after this - snapping the ends can only ever make that
    loop's job easier (by removing the one violation the model cannot be
    expected to hit exactly), never mask a real internal inconsistency."""
    if not shots:
        return

    first = shots[0]
    if first.narration_start != 0:
        drift = abs(first.narration_start)
        log = logger.warning if drift > _LARGE_SNAP_THRESHOLD_CHARS else logger.info
        log(
            "shot_planner.snapped_narration_start",
            extra={
                "scene_id": scene_id,
                "model_value": first.narration_start,
                "snapped_to": 0,
                "drift_chars": drift,
            },
        )
        first.narration_start = 0

    last = shots[-1]
    if last.narration_end != narration_len:
        drift = abs(narration_len - last.narration_end)
        log = logger.warning if drift > _LARGE_SNAP_THRESHOLD_CHARS else logger.info
        log(
            "shot_planner.snapped_narration_end",
            extra={
                "scene_id": scene_id,
                "model_value": last.narration_end,
                "snapped_to": narration_len,
                "drift_chars": drift,
            },
        )
        last.narration_end = narration_len


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

        # Structural facts, not creative decisions - snapped before any
        # check runs, so a model that is merely imprecise about the exact
        # scene-text boundary (a trailing space, a stray punctuation
        # character) never fails the whole scene over it. See
        # `_snap_narration_boundaries`'s own docstring for why this is
        # deliberately narrow: only the two outer edges are touched, and
        # every check below - including the full internal tiling walk -
        # still runs exactly as before, so a genuine gap or overlap
        # anywhere else is still a hard failure.
        _snap_narration_boundaries(shots, narration_len, scene_id=scene.id)

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


def _to_domain_shot(s: ShotPlanOutput, *, scene_id: str) -> Shot:
    # Namespaced by scene_id, never s.id alone: the Shot Planner calls the
    # model once per scene with no visibility into other scenes, and the
    # model reliably reproduces the prompt's own example id verbatim (e.g.
    # every scene's shots come back sh_01_01, sh_01_02, ...) rather than
    # inferring it should vary the prefix per scene. scene_id is guaranteed
    # unique (the Scene Planner plans every scene in one call and can see
    # the whole list), so prefixing with it makes cross-scene collisions
    # structurally impossible regardless of what the model returns.
    return Shot(
        id=f"{scene_id}_{s.id}",
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
                scene.model_copy(
                    update={"shots": [_to_domain_shot(s, scene_id=scene.id) for s in output.shots]}
                )
            )

        return planned_scenes
