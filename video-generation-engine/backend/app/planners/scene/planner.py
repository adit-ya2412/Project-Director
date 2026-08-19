"""Scene Planner agent (M5, second link in the chain). Breaks the full
script into an ordered list of scenes - narrative structure only, no
shots yet. See app/prompts/scene_planner/v1.md for the prompt
specification.

## Fragment ranges, not a retyped script (S2 hardening, 2026-08-16)

The model is asked for a CONTIGUOUS RANGE OF FRAGMENT INDICES per scene
("fragments 1 to 3"), never a retyped `narration_text` - see
`app/planners/fragments.py`'s own docstring for the full reasoning. This
is the same fix S1 already applied to the Shot Planner one level down,
because the Scene Planner had the identical defect: it was asked to
reproduce the script's own words verbatim per scene, and the join-and-
compare check that caught a mismatch was detecting the SAME kind of
failure - a model doing deterministic text reproduction - not preventing
it. On a real run it failed that check twice in a row, burning a full
planning call before the repair budget forced a permanent error.

`_to_domain_scene` converts a scene's fragment range back into the exact
script slice `Scene.narration_text` has always stored; nothing
downstream of this module changed - `Scene.narration_text`'s persisted
shape, the Shot Planner, the Asset Planner, and the Director are all
untouched.

## Composes with S1: a scene boundary is always a shot-fragment boundary

After this change the Shot Planner still re-splits each scene's own
`narration_text` into its OWN fragments (a finer-grained pass, scoped to
one scene rather than the whole script). This holds together because
`split_narration_fragments` is purely local and deterministic: a scene's
`narration_text` is an exact script slice cut at two of the SCRIPT's own
fragment boundaries, and re-running the identical splitter on that exact
substring reproduces the identical interior split points, because
`_find_split_points` only ever looks forward from its current scanning
position, and `_merge_whitespace_only_spans` only ever considers a
fragment's own content. The one place behaviour could in principle
differ is at the very edges of the substring - and it does not: a
script-level fragment boundary is, by construction, either position 0 or
the first NON-whitespace character after a split trigger, so a scene
never starts mid-whitespace; and a scene's own trailing whitespace (the
blank run before the next scene's content begins, folded onto the
PRECEDING fragment's span rather than promoted into its own) collapses
the same way whether "no more content" means "end of script" or "end of
this scene's slice", because both are simply "no further characters to
consider". A scene boundary is therefore always a valid fragment
boundary for the Shot Planner's own re-split, never a cut through the
middle of what would otherwise be one fragment.
"""

import asyncio
import math
import uuid

from app.core.config import settings
from app.core.logging import get_logger
from app.planners.act.planner import ActPlanner
from app.planners.fragments import NarrationFragment, split_narration_fragments
from app.planners.repair import run_structured_with_repair
from app.planners.scene.schemas import ScenePlannerOutput, ScenePlanOutput
from app.prompts.loader import load_prompt
from app.providers.base import PlanningLLMProvider
from app.repositories.llm_call_repository import LlmCallRepository
from app.schemas.timeline import CreativeContext, Scene
from app.utils.bounded_gather import bounded_gather, planner_concurrency

AGENT = "scene_planner"
PROMPT_VERSION = "v1"

# Same reasoning, same value as the Shot Planner's own
# `_LARGE_FRAGMENT_SNAP_THRESHOLD` (S1): fragment counts are small
# integers, unlike the character-offset drift this constant used to gate
# for the old verbatim-text design. A model choosing from a short
# NUMBERED LIST is either right, off by one (a fencepost mistake about
# whether a range is inclusive), or has misread the fragment list
# entirely. 1 sits exactly on that line.
_LARGE_FRAGMENT_SNAP_THRESHOLD = 1

logger = get_logger(__name__)


def _snap_fragment_boundaries(scenes: list[ScenePlanOutput], fragment_count: int) -> None:
    """The first scene's `fragment_start` is always 1 and the last
    scene's `fragment_end` is always `fragment_count` - structural facts
    the caller already knows, not creative decisions - so they are
    corrected here rather than validated and rejected. Mirrors the Shot
    Planner's own `_snap_fragment_boundaries` (S1) one level up; kept as
    a separate function rather than a shared import because the two
    operate on different item types (`ScenePlanOutput` vs
    `ShotPlanOutput`) and different log event names, not because the
    logic is meant to diverge.

    Deliberately narrow: only the two OUTER boundaries are touched.
    Internal gaps, overlaps, and an out-of-range fragment index are
    genuine structural errors, still caught by the validation walk that
    runs right after this."""
    if not scenes:
        return

    first = scenes[0]
    if first.fragment_start != 1:
        drift = abs(first.fragment_start - 1)
        log = logger.warning if drift > _LARGE_FRAGMENT_SNAP_THRESHOLD else logger.info
        log(
            "scene_planner.snapped_fragment_start",
            extra={
                "scene_id": first.id,
                "model_value": first.fragment_start,
                "snapped_to": 1,
                "drift_fragments": drift,
            },
        )
        first.fragment_start = 1

    last = scenes[-1]
    if last.fragment_end != fragment_count:
        drift = abs(fragment_count - last.fragment_end)
        log = logger.warning if drift > _LARGE_FRAGMENT_SNAP_THRESHOLD else logger.info
        log(
            "scene_planner.snapped_fragment_end",
            extra={
                "scene_id": last.id,
                "model_value": last.fragment_end,
                "snapped_to": fragment_count,
                "drift_fragments": drift,
            },
        )
        last.fragment_end = fragment_count


def _build_user_content(
    fragments: list[NarrationFragment], creative_context: CreativeContext, max_scenes: int
) -> str:
    numbered_fragments = "\n".join(f"{f.index}. {f.text}" for f in fragments)
    return (
        f"Script, split into {len(fragments)} numbered fragments:\n"
        f"{numbered_fragments}\n\n"
        f"Assign each scene a CONTIGUOUS RANGE of these fragment numbers via "
        f"`fragment_start`/`fragment_end` (both inclusive) - never retype the narration "
        f"text, and never split a single fragment between two scenes. Every fragment from "
        f"1 to {len(fragments)} must be covered, in order, by exactly one scene. The script "
        f"can therefore have AT MOST {len(fragments)} scene(s).\n\n"
        "Director's creative context:\n"
        f"- tone: {creative_context.tone}\n"
        f"- visual_style: {creative_context.visual_style}\n"
        f"- historical_period: {creative_context.historical_period}\n"
        f"- audience: {creative_context.audience}\n\n"
        f"Constraints: produce at most {max_scenes} scenes."
    )


def _make_validator(
    script: str,
    fragments: list[NarrationFragment],
    max_scenes: int,
    max_video_duration_s: float,
):
    fragment_count = len(fragments)

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

        # Structural facts, not creative decisions - snapped before any
        # fragment check runs, so a model that is merely imprecise about
        # the exact outer fragment number never fails the whole script
        # over it. See `_snap_fragment_boundaries`'s own docstring for
        # why this is deliberately narrow: only the two outer edges are
        # touched, and every check below - including the full tiling
        # walk - still runs exactly as before, so a genuine gap,
        # overlap, or out-of-range fragment index is still a hard
        # failure.
        _snap_fragment_boundaries(scenes, fragment_count)

        # Fragment-range tiling: replaces the old word-content
        # concatenation check. "The script cannot have more scenes than
        # fragments" is not a separate rule - it falls out of this same
        # walk for free, since it is arithmetically impossible for more
        # non-empty disjoint ranges to exist than there are fragments to
        # distribute them over (see app/planners/fragments.py's own
        # docstring).
        tiling_ok = True
        cursor = 1
        for s in scenes:
            if s.fragment_start != cursor:
                violations.append(
                    f"scene {s.id} fragment_start ({s.fragment_start}) must equal "
                    f"{cursor} - fragment ranges must be contiguous with no gaps or "
                    f"overlaps, covering fragments 1..{fragment_count}"
                )
                tiling_ok = False
            if s.fragment_end < s.fragment_start:
                violations.append(
                    f"scene {s.id} fragment_end ({s.fragment_end}) must be >= "
                    f"fragment_start ({s.fragment_start})"
                )
                tiling_ok = False
            if s.fragment_end > fragment_count:
                violations.append(
                    f"scene {s.id} fragment_end ({s.fragment_end}) exceeds the script's "
                    f"fragment count ({fragment_count})"
                )
                tiling_ok = False
            cursor = s.fragment_end + 1
        if cursor != fragment_count + 1:
            violations.append(
                f"the last scene's fragment_end ({cursor - 1}) must equal the script's "
                f"fragment count ({fragment_count}) - every fragment must be covered"
            )
            tiling_ok = False

        # Cheap backstop, kept deliberately (S2 decision, mirroring S1's
        # own outer-edge snap: "it costs nothing, and it still defends
        # against" a bug): if the tiling walk above found no violation,
        # every fragment index used below is guaranteed valid, so
        # concatenating each scene's own fragment-range slice of the
        # SCRIPT is guaranteed - by app/planners/fragments.py's own
        # lossless-reconstruction property - to reproduce the script
        # exactly. Unlike the verbatim-retyping check this replaces,
        # there is no model-introduced whitespace/casing drift left to
        # tolerate (the text is sliced by code from the script itself,
        # never retyped), so this is a plain, exact string comparison,
        # not a normalised one - a mismatch here means a bug in this
        # module's own slicing, not a model error.
        if tiling_ok:
            joined = "".join(
                script[fragments[s.fragment_start - 1].start : fragments[s.fragment_end - 1].end]
                for s in scenes
            )
            if joined != script:
                violations.append(
                    "concatenating every scene's fragment-range slice must reproduce the "
                    "script exactly - this indicates a bug in fragment slicing, not the model"
                )

        return violations

    return _validate


def _to_domain_scene(
    s: ScenePlanOutput, *, script: str, fragments: list[NarrationFragment]
) -> Scene:
    # Fragment range -> narration text: by validation time, fragment_start
    # and fragment_end are guaranteed valid 1-indexed positions within
    # `fragments` (checked above, before this ever runs), so the scene's
    # own narration_text is simply the script slice from its first
    # fragment's start to its last fragment's end - both fragment spans
    # and scene-ranges tile losslessly (app/planners/fragments.py), so
    # the composition does too.
    start = fragments[s.fragment_start - 1].start
    end = fragments[s.fragment_end - 1].end
    return Scene(
        id=s.id,
        order=s.order,
        title=s.title,
        summary=s.summary,
        emotion=s.emotion,
        narrative_purpose=s.narrative_purpose,
        narration_text=script[start:end],
        duration_s=s.duration_s,
        shots=[],
        act_id=None,
    )


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
        fragments = split_narration_fragments(script)
        if len(fragments) > settings.scene_planner_act_threshold:
            return await self._plan_hierarchical(
                project_id=project_id,
                script=script,
                fragments=fragments,
                creative_context=creative_context,
                max_scenes=max_scenes,
                max_video_duration_s=max_video_duration_s,
            )
        return await self._plan_single(
            project_id=project_id,
            script=script,
            creative_context=creative_context,
            max_scenes=max_scenes,
            max_video_duration_s=max_video_duration_s,
        )

    async def _plan_single(
        self,
        *,
        project_id: str,
        script: str,
        creative_context: CreativeContext,
        max_scenes: int,
        max_video_duration_s: float,
        db_lock: asyncio.Lock | None = None,
    ) -> list[Scene]:
        fragments = split_narration_fragments(script)
        output = await run_structured_with_repair(
            provider=self._provider,
            llm_call_repo=self._llm_call_repo,
            project_id=uuid.UUID(project_id),
            agent=AGENT,
            prompt_version=PROMPT_VERSION,
            system_prompt=load_prompt(AGENT, PROMPT_VERSION),
            user_content=_build_user_content(fragments, creative_context, max_scenes),
            response_model=ScenePlannerOutput,
            validate=_make_validator(script, fragments, max_scenes, max_video_duration_s),
            db_lock=db_lock,
        )
        return [_to_domain_scene(s, script=script, fragments=fragments) for s in output.scenes]

    async def _plan_hierarchical(
        self,
        *,
        project_id: str,
        script: str,
        fragments: list[NarrationFragment],
        creative_context: CreativeContext,
        max_scenes: int,
        max_video_duration_s: float,
    ) -> list[Scene]:
        """Path B: act pass, then per-act scene planning on re-based
        local fragment lists (never absolute indices in the prompt)."""
        n_total = len(fragments)
        acts = await ActPlanner(self._provider, self._llm_call_repo).plan(
            project_id=project_id, script=script, creative_context=creative_context
        )
        db_lock = asyncio.Lock()

        async def _one_act(act) -> list[Scene]:
            n_act = max(1, len(split_narration_fragments(act.script_slice)))
            act_max_scenes = max(1, math.ceil(max_scenes * n_act / n_total))
            act_max_duration = max_video_duration_s * n_act / n_total
            scenes = await self._plan_single(
                project_id=project_id,
                script=act.script_slice,
                creative_context=creative_context,
                max_scenes=act_max_scenes,
                max_video_duration_s=act_max_duration,
                db_lock=db_lock,
            )
            named: list[Scene] = []
            for scene in scenes:
                named.append(
                    scene.model_copy(update={"id": f"{act.id}_{scene.id}", "act_id": act.id})
                )
            return named

        gathered = await bounded_gather(acts, _one_act, concurrency=planner_concurrency())
        scenes: list[Scene] = []
        for item in gathered:
            if isinstance(item, Exception):
                raise item
            scenes.extend(item)
        return [s.model_copy(update={"order": i}) for i, s in enumerate(scenes)]
