"""Shot Planner agent (M5, third link in the chain). Fills `shots` for
every scene - one LLM call per scene, so the fragment-range and duration-
sum constraints stay scoped to something the model can actually reason
about. See app/prompts/shot_planner/v1.md for the prompt specification.

## Fragment ranges, not character offsets (M5 hardening, 2026-08-15)

The model is asked for a CONTIGUOUS RANGE OF FRAGMENT INDICES per shot
("fragments 1 to 2"), never a `narration_start`/`narration_end`
character offset - see `app/planners/fragments.py`'s own docstring
for the full reasoning (three separate incidents of unreliable model
character-arithmetic, one root cause). `_to_domain_shot` converts a
shot's fragment range back into the exact character span
`Shot.narration_span` has always stored; nothing downstream of this
module changed.

The splitter itself (`app/planners/fragments.py`) moved out of this
package in S2 (2026-08-16): the Scene Planner needed the identical
splitter for the identical reason, and there is nothing shot-specific
left in it - both planners now import the one module.

A crash mid-loop (after scene 3's shots landed, before scene 4's) is not
separately resumable within this call - `GenerateTimelineStep` only
checkpoints once, via one `append_version`, after every scene in this
loop has succeeded. A retry re-plans every scene. This is a deliberate
scope boundary (see the Implementation Guide M5 section): step-level
resumability, not sub-call-level.
"""

import asyncio
import uuid

from app.core.config import settings
from app.core.errors import PermanentError
from app.core.logging import get_logger
from app.planners.fragments import NarrationFragment, split_narration_fragments
from app.planners.repair import run_structured_with_repair
from app.planners.shot.schemas import ShotPlannerOutput, ShotPlanOutput
from app.prompts.loader import load_prompt, load_style_fragment
from app.providers.base import PlanningLLMProvider
from app.repositories.llm_call_repository import LlmCallRepository
from app.schemas.timeline import (
    Act,
    Camera,
    CameraDirection,
    CameraMovement,
    CreativeContext,
    Framing,
    Scene,
    Shot,
    Transition,
    TransitionType,
)
from app.script.styles import RenderFormat, resolve_render_format
from app.utils.bounded_gather import bounded_gather, planner_concurrency

logger = get_logger(__name__)

# Fragment counts per scene are small integers (typically well under 10),
# unlike the character-offset drift this constant used to gate: a model
# choosing from a short NUMBERED LIST is either right, off by one (a
# fencepost mistake about whether a range is inclusive), or has
# misunderstood the fragment list entirely. 1 sits exactly on that line.
_LARGE_FRAGMENT_SNAP_THRESHOLD = 1

# prompt_fixes.md §3.2: the three custom glitch transitions. Not real
# xfade names - slideshow.py branches on these. The Shot Planner runs
# per-scene, so "at most one per video" cannot be enforced in the prompt;
# `_cap_glitch_transitions` is the post-gather corrective pass.
_GLITCH_TYPES = frozenset(
    {
        TransitionType.GLITCH_SHIFT,
        TransitionType.GLITCH_TEAR,
        TransitionType.GLITCH_JITTER,
    }
)


def _cap_glitch_transitions(planned_scenes: list[Scene]) -> list[Scene]:
    """Keep the first glitch in scene/shot order; downgrade later ones
    to CUT / 0s.

    Silently correct, don't fail loudly (style_extensions.md §2.7,
    argued): the model was never *able* to see the other scenes, so a
    hard failure would punish it for missing information it was
    structurally denied - the same reasoning that moved
    `max_video_shots_per_project` from PermanentError to a downgrade
    (asset/planner.py). A glitch becoming a plain cut is a strictly
    safe degradation (`cut` is the base default).

    Deliberately NOT extended to wipeleft/fadeblack (prompt_fixes.md
    §3.2): an over-used wipe reads as showy, an over-used glitch reads
    as broken, and silently rewriting ordinary transitions is a much
    larger behavioural change than capping a deliberately-rare effect.
    """
    kept = False
    downgraded = 0
    out: list[Scene] = []
    for scene in planned_scenes:
        new_shots: list[Shot] = []
        for shot in scene.shots:
            if shot.transition_out.type in _GLITCH_TYPES:
                if kept:
                    shot = shot.model_copy(
                        update={
                            "transition_out": Transition(type=TransitionType.CUT, duration_s=0.0)
                        }
                    )
                    downgraded += 1
                else:
                    kept = True
            new_shots.append(shot)
        out.append(scene.model_copy(update={"shots": new_shots}))
    if downgraded:
        # stdlib logger - extra={}, never bare kwargs (TypeError).
        logger.warning(
            "shot_planner.glitch_cap_exceeded_downgrading",
            extra={"kept_first": True, "downgraded": downgraded},
        )
    return out


def _cap_text_cards(
    planned_scenes: list[Scene],
    *,
    min_gap: int,
    chapter_shot_ids: frozenset[str] = frozenset(),
) -> list[Scene]:
    """Enforce a project-wide minimum shot gap between text cards, with
    CHAPTER cards (A4's act-boundary titles) outranking ordinary ones.

    Walks every shot in scene/shot order and clears `text_card` on any
    ORDINARY card that lands fewer than `min_gap` shots away from the
    last kept one.

    Why this exists (prompt_fixes.md §2.1's rule, third instance): the
    prompt asks for "roughly one card every four to six shots", but the
    Shot Planner is called ONCE PER SCENE and scenes average ~4 shots -
    so each call reasonably emits one, and the whole-video rate lands at
    the per-scene rate. Measured on d3a4d00d: 17 cards / 39 shots, ~2x
    intended, and 17 stinger SFX hits with it. No wording fixes this;
    the caller cannot see the other scenes.

    Spacing, not a hard count: it keeps cards spread the way the prompt
    intends rather than keeping the first N and stranding a run of them
    at the front. Silently correct + log, per style_extensions.md §2.7 -
    the model was structurally denied the information needed to get this
    right, so failing the run would punish it for our own architecture.
    That contract is preserved here unchanged: a chapter card losing to
    the spacing rule is not a data error either, it is the same
    structural blindness with a worse consequence (A4's whole visible
    payoff silently vanishing, long_form_direction.md §3 A7), so it is
    still corrected and logged, never raised.

    **Identifying a chapter card (A7).** `chapter_shot_ids` is a set of
    `Shot.id`, not a new field on `Shot`: A4's own fragment
    (`documentary_archival.md`) instructs the model to place a chapter
    card on "this scene's first shot" for a scene told it opens an act,
    so the caller (`ShotPlanner.plan`) derives the set as the first shot
    of every scene in A6's `opening_scene_ids`. No schema change is
    needed, and there is nothing on `Shot` itself to drift out of sync
    with the fragment's own wording - the identification is exactly the
    rule the model was told to follow.

    **Precedence:**
    - A chapter card is NEVER cleared.
    - An ordinary card that collides with a chapter card yields. Only
      one direction needs an explicit correction: if an ordinary card
      was already KEPT and a chapter card then lands within `min_gap` of
      it, the ordinary card is retroactively cleared and the gap counter
      restarts from the chapter card. The other direction (an ordinary
      card arriving shortly AFTER an already-kept chapter card) falls
      out of the existing spacing rule unchanged, since the chapter card
      is already the "last kept" card by the time the ordinary one is
      checked.
    - Two chapter cards colliding are both kept - chapter cards are
      never cleared, full stop - even though §3 A7 notes this
      "realistically cannot" happen (acts are minutes apart). See
      `test_two_chapter_cards_within_the_gap_are_both_kept` in
      `test_shot_planner_text_card_cap.py` for the asserted, not
      assumed, behaviour.

    Needs no new fingerprint input: `text_card` lives on the Shot, and
    the whole timeline document is already hashed (same reasoning as
    Feature B's original text_card wiring). `chapter_shot_ids` is
    derived, not persisted.
    """
    if min_gap <= 0:
        return planned_scenes

    flat: list[Shot] = [shot for scene in planned_scenes for shot in scene.shots]
    original_cards: list[str | None] = [(s.text_card or "").strip() or None for s in flat]
    decisions: list[str | None] = list(original_cards)

    shots_since_kept: int | None = None  # None = no card kept yet
    last_kept_index: int | None = None
    last_kept_is_chapter = False
    kept_chapter = 0
    kept_ordinary = 0
    cleared_ordinary_spacing = 0
    cleared_ordinary_for_chapter = 0

    for i, shot in enumerate(flat):
        card = original_cards[i]
        if card is None:
            if shots_since_kept is not None:
                shots_since_kept += 1
            continue

        if shot.id in chapter_shot_ids:
            # A chapter card is never cleared. If the most recently kept
            # card is an ordinary one landing inside the gap, IT yields
            # instead - the ordinary card was kept first only because it
            # was planned first; the chapter card still outranks it.
            if (
                shots_since_kept is not None
                and shots_since_kept < min_gap
                and not last_kept_is_chapter
            ):
                decisions[last_kept_index] = None  # type: ignore[index]
                cleared_ordinary_for_chapter += 1
                kept_ordinary -= 1
            kept_chapter += 1
            shots_since_kept = 0
            last_kept_index = i
            last_kept_is_chapter = True
        elif shots_since_kept is None or shots_since_kept >= min_gap:
            kept_ordinary += 1
            shots_since_kept = 0
            last_kept_index = i
            last_kept_is_chapter = False
        else:
            decisions[i] = None
            cleared_ordinary_spacing += 1
            shots_since_kept += 1

    total_cleared = cleared_ordinary_spacing + cleared_ordinary_for_chapter
    if total_cleared:
        # stdlib logger - extra={}, never bare kwargs (TypeError). Split
        # by kind (A7) so this line can finally say WHICH kind of card
        # was dropped - the pre-A7 single `cleared` count could not.
        logger.warning(
            "shot_planner.text_cards_too_dense_trimmed",
            extra={
                "kept_chapter": kept_chapter,
                "kept_ordinary": kept_ordinary,
                "cleared_ordinary_spacing": cleared_ordinary_spacing,
                "cleared_ordinary_for_chapter": cleared_ordinary_for_chapter,
                "min_gap": min_gap,
            },
        )

    out: list[Scene] = []
    idx = 0
    for scene in planned_scenes:
        new_shots: list[Shot] = []
        for shot in scene.shots:
            new_card = decisions[idx]
            if new_card != original_cards[idx]:
                shot = shot.model_copy(update={"text_card": new_card})
            new_shots.append(shot)
            idx += 1
        out.append(scene.model_copy(update={"shots": new_shots}))
    return out


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
    scene: Scene,
    creative_context: CreativeContext,
    fragments: list[NarrationFragment],
    *,
    suppress_camera_language: bool = False,
    act: Act | None = None,
    act_ordinal: tuple[int, int] | None = None,
    opens_act: bool = False,
    render_format: RenderFormat | None = None,
) -> str:
    numbered_fragments = "\n".join(f"{f.index}. {f.text}" for f in fragments)
    camera_line = (
        ""
        if suppress_camera_language
        else f"- camera_language: {creative_context.camera_language}\n"
    )
    # long_form_direction.md A6 (2026-08-31) added act + canvas context
    # gated TOGETHER on `act is not None` (Path B / hierarchical scene
    # planning - Path A projects, <=70 fragments, never stamp `act_id`).
    # A5 (2026-08-31) deliberately DECOUPLES the two, per its own §3
    # instruction: canvas resolution has nothing to do with act presence
    # (A5's vertical-pan gate needs it on every project, not just Path
    # B), so `canvas_line` is now built from `render_format` alone. This
    # breaks A6's byte-identity property on purpose - see
    # `test_shot_planner_context.py`'s updated Path-A test and A5's own
    # §7 log entry for why that is an accepted, one-time cost here.
    canvas_line = ""
    if render_format is not None:
        canvas_line = (
            f"- canvas: {render_format.width}x{render_format.height} "
            f"({render_format.aspect_ratio})\n"
        )
    long_form_context = ""
    if act is not None:
        ordinal_line = ""
        if act_ordinal is not None:
            position, total = act_ordinal
            ordinal_line = f"- act position: act {position} of {total}\n"
        long_form_context = (
            "\n"
            "Long-form context:\n"
            f"- act: {act.title}\n"
            f"{ordinal_line}"
            f"- opens this act: {'yes' if opens_act else 'no'}\n"
            f"{canvas_line}"
        )
    elif canvas_line:
        # No act (Path A, or a Path B project whose scene has none) but a
        # canvas WAS resolved - A5's prompt wording (v1.md) reads this to
        # decide whether a vertical pan has anywhere to travel. Same
        # heading as the act-bearing block above so there is only ever
        # one "Long-form context:" shape in this function's output.
        long_form_context = "\nLong-form context:\n" f"{canvas_line}"
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
        f"{camera_line}"
        f"{long_form_context}"
    )


def _make_validator(
    scene: Scene,
    fragments: list[NarrationFragment],
    min_shot_duration_s: float,
    max_shot_duration_s: float,
    render_format: RenderFormat,
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
            is_split = s.camera.movement == CameraMovement.SPLIT_FRAME
            has_secondary = bool(s.secondary_prompt.strip())
            if is_split and not has_secondary:
                violations.append(
                    f"shot {s.id}: split_frame needs a non-empty secondary_prompt "
                    "(the bottom panel) - do not put both subjects in `prompt`"
                )
            if has_secondary and not is_split:
                violations.append(
                    f"shot {s.id}: secondary_prompt is only for split_frame, "
                    f"got {s.camera.movement.value}"
                )
            if is_split and s.framing != Framing.SPLIT:
                violations.append(
                    f"shot {s.id}: split_frame must use framing=split, got {s.framing.value}"
                )
            if s.framing == Framing.SPLIT and not is_split:
                violations.append(
                    f"shot {s.id}: framing=split is only for split_frame, "
                    f"got {s.camera.movement.value}"
                )
            # A5 (long_form_direction.md §3): vertical pan only makes
            # sense on a landscape canvas - a tall subject on a wide
            # frame. Hard-fail (not a silent downgrade like
            # `_cap_glitch_transitions`/`_cap_text_cards`): those two
            # exist because the model is called once per scene and
            # cannot see the OTHER scenes it needs to self-correct
            # against. This check needs nothing outside the current
            # call - the canvas line is already IN this scene's own
            # prompt (`_build_user_content`) - so the model had the
            # information and still made an out-of-band choice; a hard
            # failure gives it that feedback back and lets it correct
            # itself (`run_structured_with_repair`'s retry), rather than
            # silently rewriting a directed creative decision (canon 3.1)
            # into a movement/direction the model never asked for.
            if (
                s.camera.direction in (CameraDirection.UP, CameraDirection.DOWN)
                and not render_format.is_landscape
            ):
                violations.append(
                    f"shot {s.id}: camera.direction={s.camera.direction.value} is a "
                    "vertical pan, which is only legal on a landscape canvas (a tall "
                    "subject on a wide frame) - this project's canvas is "
                    f"{render_format.width}x{render_format.height} "
                    f"({render_format.aspect_ratio}), a portrait frame with nowhere for "
                    "a vertical pan to travel"
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
        secondary_prompt=s.secondary_prompt,
        # Feature B (§4.4): empty string -> None, the persisted model's
        # "no card" shape (`derive_text_card_cues` treats both alike).
        text_card=s.text_card.strip() or None,
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
        render_style: str | None = None,
        acts: list[Act] | None = None,
        frame_aspect: str | None = None,
    ) -> list[Scene]:
        system_prompt = load_prompt(self.name, self._PROMPT_VERSION)
        # Track B (2026-08-17), plan §4.3: one base prompt plus one
        # optional style fragment, composed here rather than as a second
        # full prompt file per style - `load_style_fragment` returns
        # `None` for a style with nothing planner-specific to say
        # (`documentary_archival`, `stillness`, or no style at all),
        # leaving `system_prompt` byte-identical to what every project
        # before this field existed already received.
        style_fragment = load_style_fragment(self.name, render_style)
        if style_fragment:
            system_prompt = f"{system_prompt}\n\n{style_fragment}"
        db_lock = asyncio.Lock()

        # long_form_direction.md A6 (2026-08-31, RV2 "resolve once, thread
        # explicitly"): the canvas is one value for the whole project, not
        # per scene, so it is resolved exactly once here rather than
        # inside the per-scene closure. `acts` is `[]` on every Path A
        # project (§3 A6) and every timeline predating A3, so all three
        # lookups below are empty and every scene falls through to the
        # `act is None` branch in `_build_user_content` - byte-identical
        # to pre-A6 output.
        acts_by_id = {a.id: a for a in (acts or [])}
        acts_sorted = sorted((acts or []), key=lambda a: a.order)
        act_ordinals = {a.id: (i + 1, len(acts_sorted)) for i, a in enumerate(acts_sorted)}
        opening_scene_ids: set[str] = set()
        seen_act_ids: set[str] = set()
        for s in sorted(scenes, key=lambda sc: sc.order):
            if s.act_id and s.act_id not in seen_act_ids:
                seen_act_ids.add(s.act_id)
                opening_scene_ids.add(s.id)
        render_format = resolve_render_format(render_style, frame_aspect=frame_aspect)

        async def _one_scene(scene: Scene) -> Scene:
            fragments = split_narration_fragments(scene.narration_text)
            act = acts_by_id.get(scene.act_id) if scene.act_id else None
            output = await run_structured_with_repair(
                provider=self._provider,
                llm_call_repo=self._llm_call_repo,
                project_id=uuid.UUID(project_id),
                agent=self.name,
                prompt_version=self._PROMPT_VERSION,
                system_prompt=system_prompt,
                user_content=_build_user_content(
                    scene,
                    creative_context,
                    fragments,
                    # Q6: a style fragment that owns camera must not share
                    # the request with the Director's camera_language —
                    # the two contradict with no stated precedence.
                    suppress_camera_language=style_fragment is not None,
                    act=act,
                    act_ordinal=act_ordinals.get(scene.act_id) if act is not None else None,
                    opens_act=scene.id in opening_scene_ids,
                    # A5 (long_form_direction.md §3): decoupled from `act`
                    # - resolved once above, unconditionally, so every
                    # project (Path A included) learns its own canvas.
                    render_format=render_format,
                ),
                response_model=ShotPlannerOutput,
                validate=_make_validator(
                    scene, fragments, min_shot_duration_s, max_shot_duration_s, render_format
                ),
                db_lock=db_lock,
            )
            return scene.model_copy(
                update={
                    "shots": [
                        _to_domain_shot(s, scene_id=scene.id, fragments=fragments)
                        for s in output.shots
                    ]
                }
            )

        gathered = await bounded_gather(scenes, _one_scene, concurrency=planner_concurrency())
        planned_scenes: list[Scene] = []
        for item in gathered:
            if isinstance(item, Exception):
                raise item
            planned_scenes.append(item)
        # Cap check AFTER the gather (Track C §2.4) — a running total
        # inside the concurrent body would race.
        total_shots = sum(len(s.shots) for s in planned_scenes)
        if total_shots > max_shots_per_project:
            raise PermanentError(
                f"shot planner exceeded max_shots_per_project ({max_shots_per_project}) "
                f"- {total_shots} shots planned"
            )
        # Both post-gather corrective passes for whole-project rates no
        # single per-scene call can see (prompt_fixes.md §2.1).
        capped = _cap_glitch_transitions(planned_scenes)
        # A7 (long_form_direction.md §3): a chapter card is A4's fragment
        # instructing the model to put it on an act-opening scene's FIRST
        # shot - so identify one by shot id, not a new Shot field. Reuse
        # `opening_scene_ids` (A6, computed above) rather than
        # recomputing "which scene opens an act" a second way.
        chapter_shot_ids = frozenset(
            scene.shots[0].id
            for scene in capped
            if scene.id in opening_scene_ids and scene.shots
        )
        return _cap_text_cards(
            capped,
            min_gap=settings.text_card_min_shot_gap,
            chapter_shot_ids=chapter_shot_ids,
        )
