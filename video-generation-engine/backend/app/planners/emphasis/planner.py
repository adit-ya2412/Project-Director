"""Whole-film emphasis planner (retention_fast_kinetic_text.md K9).

One LLM call after the shot plan and before narration. Sees every
scene, fragment, and shot; emits every `EmphasisCue` plus the
per-project palette pair. Timing is a fragment INDEX — this pass
never sees or guesses seconds (K2 resolves `offset_s` later).

v1 authors `stamp` / `counter` / `pivot` only. `EmphasisDevice` stays
wide (Decision 8); unknown devices are dropped and logged, not a
failed run. `text_register` is derived in code from Decision 4, never
asked of the model.

Pure mapping: `apply_emphasis_plan` returns a copy. Never mutates
in place. Density / citation / blockers are K3's job
(`enforce_emphasis_rules`), called by the step after this returns.
Lexical `attach_pivot_cue` is the pivot backstop if the model misses
the turn.
"""

from __future__ import annotations

import uuid

from pydantic import ValidationError

from app.core.logging import get_logger
from app.planners.caption_romanizer.planner import contains_devanagari
from app.planners.emphasis.schemas import (
    EmphasisCuePlanOutput,
    EmphasisPlannerOutput,
    EmphasisValuePlanOutput,
)
from app.planners.fragments import NarrationFragment, split_narration_fragments
from app.planners.repair import run_structured_with_repair
from app.prompts.loader import load_prompt
from app.providers.base import PlanningLLMProvider
from app.repositories.llm_call_repository import LlmCallRepository
from app.schemas.timeline import (
    EmphasisCue,
    EmphasisDevice,
    EmphasisPalette,
    EmphasisRegister,
    EmphasisValue,
    Scene,
    Shot,
    Timeline,
)
from app.script.styles import resolve_emphasis_hook_s
from app.timeline.duration import compute_timeline_duration
from app.timeline.emphasis_rules import shot_blocks_emphasis_cue
from app.timeline.pivot import attach_pivot_cue, detect_pivot

logger = get_logger(__name__)

AGENT = "emphasis"
PROMPT_VERSION = "v1"

# K14.4: authoring target multiplier (was 10.0). Necessary-but-not-
# sufficient without the hook wording in K14.3.
_TARGET_CUES_PER_MINUTE = 12.0
# K14.3 / K14.4: authoring floor inside the hook window. K3 cannot
# invent cues; this integer is what the model obeys.
_HOOK_MIN_CUES = 3
_HOOK_FIRST_CUE_DEADLINE_S = 1.5

_V1_DEVICES = frozenset({"stamp", "counter", "pivot"})
_PIVOT_CANONICAL = {
    "lekin": "लेकिन",
    "लेकिन": "लेकिन",
    "but": "लेकिन",
    "magar": "मगर",
    "मगर": "मगर",
}


def derive_text_register(device: str, text: str) -> EmphasisRegister:
    """Decision 4: fixed role table, not a planner choice."""
    if device == "pivot":
        return EmphasisRegister.HI
    if device == "counter":
        return EmphasisRegister.EN
    return EmphasisRegister.HI if contains_devanagari(text) else EmphasisRegister.EN


def _canonical_pivot_text(text: str) -> str:
    stripped = text.strip()
    return _PIVOT_CANONICAL.get(stripped.lower(), stripped)


def _shot_index(timeline: Timeline) -> dict[str, tuple[Scene, Shot]]:
    return {shot.id: (scene, shot) for scene in timeline.scenes for shot in scene.shots}


def _fragments_by_scene(timeline: Timeline) -> dict[str, list[NarrationFragment]]:
    return {
        scene.id: split_narration_fragments(scene.narration_text or "")
        for scene in timeline.scenes
    }


def _shot_fragment_range(
    shot: Shot, fragments: list[NarrationFragment]
) -> tuple[int, int] | None:
    if shot.narration_span is None or not fragments:
        return None
    start, end = shot.narration_span
    covered = [fragment for fragment in fragments if fragment.start < end and fragment.end > start]
    if not covered:
        return None
    return covered[0].index, covered[-1].index


def _short(text: str, limit: int = 160) -> str:
    stripped = text.strip()
    if len(stripped) <= limit:
        return stripped
    return stripped[: limit - 1] + "…"


def _density_target_line(timeline: Timeline, duration_s: float) -> str:
    """Authoring target string. K14.3 names the hook; K14.4 raises 12.0."""
    total = max(1, round(duration_s / 60.0 * _TARGET_CUES_PER_MINUTE))
    hook_s = resolve_emphasis_hook_s(timeline.metadata.render_style)
    if hook_s is None or hook_s <= 0:
        return (
            f"Target cue count: {total} (band 8-12 per minute; one cue per shot; "
            "space them — several shots of rest between cues)."
        )
    hook_min = min(_HOOK_MIN_CUES, total)
    body = max(0, total - hook_min)
    return (
        f"Target cue count: {total} = at least {hook_min} in the first "
        f"{hook_s:.1f}s hook + {body} in the body "
        f"(multiplier {_TARGET_CUES_PER_MINUTE:.1f}/min). "
        f"The first seconds are worth more than the last — front-load. "
        f"Put the first cue inside ~{_HOOK_FIRST_CUE_DEADLINE_S:.1f}s. "
        f"Inside the hook, consecutive shots may both carry a cue. "
        f"Body uses the remaining {body} with several shots of rest "
        f"between cues (gap 3). One cue per shot."
    )


def _build_user_content(timeline: Timeline) -> str:
    shots = timeline.all_shots()
    duration_s = compute_timeline_duration(shots)
    density_line = _density_target_line(timeline, duration_s)
    fragments_by_scene = _fragments_by_scene(timeline)
    hit = detect_pivot(timeline)
    if hit is None:
        turn_line = (
            "Lexical turn: none. Do not emit a pivot cue; there is no turn word "
            "on an attachable shot."
        )
    else:
        turn_line = (
            f"Lexical turn: shot {hit.shot_id} covers the pivot word {hit.matched!r} "
            f"at fragment {hit.anchor_fragment} of its scene. You MUST emit a "
            f"pivot cue on that shot (text {hit.text!r}, anchor_fragment "
            f"{hit.anchor_fragment})."
        )

    scene_blocks: list[str] = []
    for scene in sorted(timeline.scenes, key=lambda item: item.order):
        fragments = fragments_by_scene[scene.id]
        numbered = "\n".join(f"  {fragment.index}. {fragment.text}" for fragment in fragments)
        shot_lines: list[str] = []
        for shot in sorted(scene.shots, key=lambda item: item.order):
            span = _shot_fragment_range(shot, fragments)
            frag = f"{span[0]}-{span[1]}" if span is not None else "?"
            card = shot.text_card or ""
            prompt = _short(shot.prompt or "")
            graphic = "true" if shot.picture_is_graphic else "false"
            intent = shot.intent.value if shot.intent is not None else ""
            shot_lines.append(
                f"  - id={shot.id}  duration_s={shot.duration_s:.2f}  "
                f"fragments={frag}  intent={intent}  "
                f"picture_is_graphic={graphic}  text_card={card!r}  "
                f"prompt={prompt!r}"
            )
        scene_blocks.append(
            f"Scene {scene.id} (order {scene.order})\n"
            f"Narration:\n{scene.narration_text or ''}\n"
            f"Fragments (1-indexed within this scene):\n{numbered or '  (none)'}\n"
            f"Shots:\n" + ("\n".join(shot_lines) if shot_lines else "  (none)")
        )

    ctx = timeline.creative_context
    world_lines = [
        f"- tone: {ctx.tone}" if ctx.tone else "",
        f"- visual_style: {ctx.visual_style}" if ctx.visual_style else "",
        f"- historical_period: {ctx.historical_period}" if ctx.historical_period else "",
    ]
    world = "\n".join(line for line in world_lines if line)

    return (
        f"Film duration_s: {duration_s:.2f}\n"
        f"Shot count: {len(shots)}\n"
        f"{density_line}\n"
        f"{turn_line}\n"
        "Use each shot id EXACTLY as written (already namespaced with the "
        "scene id). anchor_fragment and cited_fragment are 1-indexed "
        "within that shot's SCENE, never film-global, never seconds.\n\n"
        f"World (for the palette, not for the cues):\n{world or '- (unset)'}\n\n"
        + "\n\n".join(scene_blocks)
    )


def _make_validator(timeline: Timeline):
    index = _shot_index(timeline)
    fragments_by_scene = _fragments_by_scene(timeline)

    def _validate(output: EmphasisPlannerOutput) -> list[str]:
        violations: list[str] = []
        seen: dict[str, int] = {}
        for i, cue in enumerate(output.cues):
            loc = f"cues[{i}]"
            if cue.shot_id in seen:
                violations.append(
                    f"{loc}.shot_id {cue.shot_id!r} duplicates cues[{seen[cue.shot_id]}]; "
                    "one cue per shot"
                )
            else:
                seen[cue.shot_id] = i
            pair = index.get(cue.shot_id)
            if pair is None:
                violations.append(
                    f"{loc}.shot_id {cue.shot_id!r} is not a shot on this timeline"
                )
                continue
            scene, shot = pair
            fragments = fragments_by_scene[scene.id]
            n = len(fragments)
            if cue.anchor_fragment < 1 or (n and cue.anchor_fragment > n):
                violations.append(
                    f"{loc}.anchor_fragment {cue.anchor_fragment} is outside "
                    f"scene {scene.id} fragments 1..{n}"
                )
            span = _shot_fragment_range(shot, fragments)
            if span is not None and not (span[0] <= cue.anchor_fragment <= span[1]):
                violations.append(
                    f"{loc}.anchor_fragment {cue.anchor_fragment} is not in "
                    f"shot {shot.id} fragment range {span[0]}-{span[1]}"
                )
            for j, value in enumerate(cue.values):
                if value.cited_fragment < 1 or (n and value.cited_fragment > n):
                    violations.append(
                        f"{loc}.values[{j}].cited_fragment {value.cited_fragment} "
                        f"is outside scene {scene.id} fragments 1..{n}"
                    )
        return violations

    return _validate


def _map_values(entries: list[EmphasisValuePlanOutput]) -> list[EmphasisValue]:
    mapped: list[EmphasisValue] = []
    for entry in entries:
        mapped.append(
            EmphasisValue(
                value=entry.value,
                unit=entry.unit.strip() or None,
                cited_fragment=entry.cited_fragment,
            )
        )
    return mapped


def _map_cue(planned: EmphasisCuePlanOutput, *, shot: Shot) -> EmphasisCue | None:
    device_name = planned.device.strip().lower()
    if device_name not in _V1_DEVICES:
        logger.info(
            "emphasis.skipped_device",
            extra={"shot_id": planned.shot_id, "device": planned.device},
        )
        return None
    blocked = shot_blocks_emphasis_cue(shot)
    if blocked is not None:
        logger.info(
            "emphasis.skipped_blocked_shot",
            extra={"shot_id": shot.id, "device": device_name, "reason": blocked},
        )
        return None
    if shot.emphasis_cue is not None:
        logger.info(
            "emphasis.skipped_already_has_cue",
            extra={"shot_id": shot.id, "device": device_name},
        )
        return None
    text = planned.text.strip()
    if device_name == "pivot":
        text = _canonical_pivot_text(text)
    if not text:
        logger.info(
            "emphasis.skipped_empty_text",
            extra={"shot_id": shot.id, "device": device_name},
        )
        return None
    values = _map_values(planned.values) if device_name == "counter" else []
    if device_name == "counter" and not values:
        logger.info(
            "emphasis.skipped_empty_counter_values",
            extra={"shot_id": shot.id},
        )
        return None
    replaced = planned.replaced_text.strip() or None
    return EmphasisCue(
        device=EmphasisDevice(device_name),
        anchor_fragment=planned.anchor_fragment,
        text=text,
        text_register=derive_text_register(device_name, text),
        values=values,
        replaced_text=replaced,
    )


def apply_emphasis_plan(timeline: Timeline, output: EmphasisPlannerOutput) -> Timeline:
    """Map planner output onto a copy, then the lexical pivot backstop.

    Does not run K3. Unknown devices, unknown shots, blocked shots,
    empty counters, and empty text are skipped and logged. Palette is
    written only when `EmphasisPalette` accepts both hexes (near-white
    `pivot_ground` is rejected by that model). Never mutates `timeline`.
    """
    copy = timeline.model_copy(deep=True)
    index = _shot_index(copy)
    for planned in output.cues:
        pair = index.get(planned.shot_id)
        if pair is None:
            logger.info(
                "emphasis.skipped_unknown_shot",
                extra={"shot_id": planned.shot_id, "device": planned.device},
            )
            continue
        shot = pair[1]
        cue = _map_cue(planned, shot=shot)
        if cue is None:
            continue
        shot.emphasis_cue = cue

    if not any(
        shot.emphasis_cue is not None and shot.emphasis_cue.device is EmphasisDevice.PIVOT
        for shot in copy.all_shots()
    ):
        copy = attach_pivot_cue(copy)

    try:
        copy.metadata.emphasis_palette = EmphasisPalette(
            accent=output.accent,
            pivot_ground=output.pivot_ground,
        )
    except ValidationError:
        logger.info(
            "emphasis.palette_rejected",
            extra={"accent": output.accent, "pivot_ground": output.pivot_ground},
        )
    return copy


class EmphasisPlanner:
    name = AGENT

    def __init__(self, provider: PlanningLLMProvider, llm_call_repo: LlmCallRepository) -> None:
        self._provider = provider
        self._llm_call_repo = llm_call_repo

    async def plan(self, *, project_id: str, timeline: Timeline) -> Timeline:
        """Return a copy with cues and (maybe) a palette. Does not enforce K3."""
        output = await run_structured_with_repair(
            provider=self._provider,
            llm_call_repo=self._llm_call_repo,
            project_id=uuid.UUID(project_id),
            agent=AGENT,
            prompt_version=PROMPT_VERSION,
            system_prompt=load_prompt(AGENT, PROMPT_VERSION),
            user_content=_build_user_content(timeline),
            response_model=EmphasisPlannerOutput,
            validate=_make_validator(timeline),
        )
        return apply_emphasis_plan(timeline, output)
