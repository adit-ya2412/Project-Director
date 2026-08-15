"""Shot Planner agent (M5, third link in the chain). Fills `shots` for
every scene - one LLM call per scene, so the fragment-range and duration-
sum constraints stay scoped to something the model can actually reason
about. See app/prompts/shot_planner/v1.md for the prompt specification.

## Fragment ranges, not character offsets (M5 hardening, 2026-08-15)

The model is asked for a CONTIGUOUS RANGE OF FRAGMENT INDICES per shot
("fragments 1 to 2"), never a `narration_start`/`narration_end`
character offset - see `app/planners/shot/fragments.py`'s own docstring
for the full reasoning (three separate incidents of unreliable model
character-arithmetic, one root cause). `_to_domain_shot` converts a
shot's fragment range back into the exact character span
`Shot.narration_span` has always stored; nothing downstream of this
module changed.

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
from app.planners.shot.fragments import NarrationFragment, split_narration_fragments
from app.planners.shot.schemas import ShotPlannerOutput, ShotPlanOutput
from app.prompts.loader import load_prompt
from app.providers.base import PlanningLLMProvider
from app.repositories.llm_call_repository import LlmCallRepository
from app.schemas.timeline import Camera, CreativeContext, Scene, Shot, Transition

logger = get_logger(__name__)

# Fragment counts per scene are small integers (typically well under 10),
# unlike the character-offset drift this constant used to gate: a model
# choosing from a short NUMBERED LIST is either right, off by one (a
# fencepost mistake about whether a range is inclusive), or has
# misunderstood the fragment list entirely. 1 sits exactly on that line.
_LARGE_FRAGMENT_SNAP_THRESHOLD = 1


def _snap_fragment_boundaries(
    shots: list[ShotPlanOutput], fragment_count: int, *, scene_id: str
) -> None:
    """The first shot's `fragment_start` is always 1 and the last shot's
    `fragment_end` is always `fragment_count` - structural facts the
    caller already knows, not creative decisions - so they are corrected
    here rather than validated and rejected, the same reasoning (and the
    same function's own earlier life) as the character-offset version
    this replaced. Kept explicitly as a backstop even though fragment
    ranges make a large miss far less likely than raw character
    offsets ever were: it costs nothing, and it still defends against a
    malformed range at either end.

    Deliberately narrow: only the two OUTER boundaries are touched.
    Internal gaps, overlaps, and an out-of-range fragment index are
    genuine structural errors, still caught by the validation walk that
    runs right after this."""
    if not shots:
        return

    first = shots[0]
    if first.fragment_start != 1:
        drift = abs(first.fragment_start - 1)
        log = logger.warning if drift > _LARGE_FRAGMENT_SNAP_THRESHOLD else logger.info
        log(
            "shot_planner.snapped_fragment_start",
            extra={
                "scene_id": scene_id,
                "model_value": first.fragment_start,
                "snapped_to": 1,
                "drift_fragments": drift,
            },
        )
        first.fragment_start = 1

    last = shots[-1]
    if last.fragment_end != fragment_count:
        drift = abs(fragment_count - last.fragment_end)
        log = logger.warning if drift > _LARGE_FRAGMENT_SNAP_THRESHOLD else logger.info
        log(
            "shot_planner.snapped_fragment_end",
            extra={
                "scene_id": scene_id,
                "model_value": last.fragment_end,
                "snapped_to": fragment_count,
                "drift_fragments": drift,
            },
        )
        last.fragment_end = fragment_count


def _build_user_content(
    scene: Scene, creative_context: CreativeContext, fragments: list[NarrationFragment]
) -> str:
    numbered_fragments = "\n".join(f"{f.index}. {f.text}" for f in fragments)
    return (
        f"Scene: {scene.title}\n"
        f"Narrative purpose: {scene.narrative_purpose}\n"
        f"Emotion: {scene.emotion}\n"
        f"Target scene duration_s: {scene.duration_s}\n"
        f"This scene's narration, split into {len(fragments)} numbered fragments:\n"
        f"{numbered_fragments}\n\n"
        f"Assign each shot a CONTIGUOUS RANGE of these fragment numbers via "
        f"`fragment_start`/`fragment_end` (both inclusive) - never a character offset, "
        f"and never split a single fragment between two shots. Every fragment from 1 to "
        f"{len(fragments)} must be covered, in order, by exactly one shot. This scene can "
        f"therefore have AT MOST {len(fragments)} shot(s).\n\n"
        "Director's creative context:\n"
        f"- historical_period: {creative_context.historical_period}\n"
        f"- visual_style: {creative_context.visual_style}\n"
        f"- camera_language: {creative_context.camera_language}\n"
    )


def _make_validator(
    scene: Scene,
    fragments: list[NarrationFragment],
    min_shot_duration_s: float,
    max_shot_duration_s: float,
):
    fragment_count = len(fragments)

    def _validate(output: ShotPlannerOutput) -> list[str]:
        violations: list[str] = []
        shots = output.shots

        if not shots:
            violations.append("shots must not be empty")
            return violations

        # Structural facts, not creative decisions - snapped before any
        # check runs, so a model that is merely imprecise about the exact
        # outer fragment number never fails the whole scene over it. See
        # `_snap_fragment_boundaries`'s own docstring for why this is
        # deliberately narrow: only the two outer edges are touched, and
        # every check below - including the full tiling walk - still
        # runs exactly as before, so a genuine gap, overlap, or
        # out-of-range fragment index is still a hard failure.
        _snap_fragment_boundaries(shots, fragment_count, scene_id=scene.id)

        ids = [s.id for s in shots]
        if len(ids) != len(set(ids)):
            violations.append("shot ids must be unique within the scene")

        expected_order = list(range(len(shots)))
        if [s.order for s in shots] != expected_order:
            violations.append(f"shot order fields must be exactly {expected_order}, in list order")

        # Fragment-range tiling: replaces the old character-offset cursor
        # walk. "A scene cannot have more shots than fragments" is not a
        # separate rule - it falls out of this same walk for free, since
        # it is arithmetically impossible for more non-empty disjoint
        # ranges to exist than there are fragments to distribute them
        # over (see app/planners/shot/fragments.py's own docstring).
        cursor = 1
        for s in shots:
            if s.fragment_start != cursor:
                violations.append(
                    f"shot {s.id} fragment_start ({s.fragment_start}) must equal "
                    f"{cursor} - fragment ranges must be contiguous with no gaps or "
                    f"overlaps, covering fragments 1..{fragment_count}"
                )
            if s.fragment_end < s.fragment_start:
                violations.append(
                    f"shot {s.id} fragment_end ({s.fragment_end}) must be >= "
                    f"fragment_start ({s.fragment_start})"
                )
            if s.fragment_end > fragment_count:
                violations.append(
                    f"shot {s.id} fragment_end ({s.fragment_end}) exceeds this scene's "
                    f"fragment count ({fragment_count})"
                )
            cursor = s.fragment_end + 1
        if cursor != fragment_count + 1:
            violations.append(
                f"the last shot's fragment_end ({cursor - 1}) must equal this scene's "
                f"fragment count ({fragment_count}) - every fragment must be covered"
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


def _to_domain_shot(
    s: ShotPlanOutput, *, scene_id: str, fragments: list[NarrationFragment]
) -> Shot:
    # Namespaced by scene_id, never s.id alone: the Shot Planner calls the
    # model once per scene with no visibility into other scenes, and the
    # model reliably reproduces the prompt's own example id verbatim (e.g.
    # every scene's shots come back sh_01_01, sh_01_02, ...) rather than
    # inferring it should vary the prefix per scene. scene_id is guaranteed
    # unique (the Scene Planner plans every scene in one call and can see
    # the whole list), so prefixing with it makes cross-scene collisions
    # structurally impossible regardless of what the model returns.
    #
    # Fragment range -> character span: by validation time, fragment_start
    # and fragment_end are guaranteed valid 1-indexed positions within
    # `fragments` (checked above, before this ever runs), so the shot's
    # own span is simply its first fragment's start joined to its last
    # fragment's end - both fragment spans and shot-ranges tile losslessly
    # (app/planners/shot/fragments.py), so the composition does too.
    start = fragments[s.fragment_start - 1].start
    end = fragments[s.fragment_end - 1].end
    return Shot(
        id=f"{scene_id}_{s.id}",
        order=s.order,
        intent=s.intent,
        intent_text=s.intent_text,
        narration_span=(start, end),
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
            fragments = split_narration_fragments(scene.narration_text)
            output = await run_structured_with_repair(
                provider=self._provider,
                llm_call_repo=self._llm_call_repo,
                project_id=uuid.UUID(project_id),
                agent=self.name,
                prompt_version=self._PROMPT_VERSION,
                system_prompt=system_prompt,
                user_content=_build_user_content(scene, creative_context, fragments),
                response_model=ShotPlannerOutput,
                validate=_make_validator(
                    scene, fragments, min_shot_duration_s, max_shot_duration_s
                ),
            )
            total_shots += len(output.shots)
            if total_shots > max_shots_per_project:
                raise PermanentError(
                    f"shot planner exceeded max_shots_per_project ({max_shots_per_project}) "
                    f"after scene {scene.id} - {total_shots} shots planned so far"
                )
            planned_scenes.append(
                scene.model_copy(
                    update={
                        "shots": [
                            _to_domain_shot(s, scene_id=scene.id, fragments=fragments)
                            for s in output.shots
                        ]
                    }
                )
            )

        return planned_scenes
