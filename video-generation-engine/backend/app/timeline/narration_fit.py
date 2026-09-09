"""narration_fit.py — the master clock (M8 step 2, D1 + D5).

Given a scene's real ElevenLabs alignment and its shots' `narration_span`s,
compute each shot's real spoken duration and reconcile it into `duration_s`.
This is the ONE place the arithmetic derived below lives; both
`NarrationStep` (which calls this) and the tests that prove it import from
here, never re-derive it.

## Why a shot's duration isn't simply `end_time - start_time`

The implementation guide's simple version of this ("a shot's true spoken
duration is a direct index lookup — `character_end_times_seconds[end - 1] -
character_start_times_seconds[start]`") is correct for a single isolated
shot, but summing that formula across a scene's shots does NOT reliably
reproduce the scene's real total spoken duration. If the TTS engine leaves
even a small gap between one character's end time and the next character's
start time (a breath, a pause after punctuation — nothing in the ElevenLabs
contract rules this out), that gap falls between two shots and is silently
uncounted by either one, under-stating the scene's total.

So this module uses **shot boundaries, not shot slices**: shot i's window
runs from the moment its own first character starts being spoken to the
moment the NEXT shot's first character starts (or, for a scene's last shot,
to the moment the scene's audio actually ends). Formally, for a scene whose
shots (sorted by `order`) tile `narration_text` with no gap and no overlap —
shot 1 spans `[0, e_1)`, shot 2 spans `[e_1, e_2)`, ..., shot k spans
`[e_{k-1}, N)` — define:

    onset(shot_j)  = character_start_times_seconds[start_j]
    offset(shot_j) = character_start_times_seconds[start_{j+1}]   for j < k
    offset(shot_k) = character_end_times_seconds[N - 1]           (last shot)

    spoken(shot_j) = offset(shot_j) - onset(shot_j)

This telescopes by construction: `sum(spoken(shot_j) for j in 1..k) ==
offset(shot_k) - onset(shot_1) == character_end_times_seconds[N-1] -
character_start_times_seconds[0]`, i.e. exactly the scene's real total
narrated duration — regardless of any pause structure inside the audio.
Any inter-line silence is attributed to the shot that is still on screen
during it (the shot holds until the next line begins), which is also the
natural editorial reading of "on screen for as long as this shot's line is
being spoken."

## Why the reconciled `duration_s` still isn't just `spoken(shot)`

`compute_timeline_duration` (D5) subtracts every non-hard-cut transition's
`overlap` once, exactly like a real crossfade: shot i+1 in a run starts
`overlap` seconds before shot i's own footage ends, so the RENDERED length
of a run is shorter than the naive sum of its shots' `duration_s`. If we
set `duration_s = spoken(shot)` directly, every transition in the timeline
would silently steal `overlap` seconds from the total, and the render would
finish before the narration does — drifting further with every transition,
exactly the "mysterious drift" the implementation guide warns about.

The fix mirrors what the Shot Planner already does when it originally
proposes durations that must survive D5's arithmetic (bake the
compensation into the number D5 is going to shrink): every shot that
FOLLOWS a non-hard-cut transition gets its `duration_s` inflated by exactly
that incoming transition's overlap, cancelling the subtraction before it
happens. Concretely, grouping shots into runs exactly the way
`duration.group_into_runs` already does (the same grouping D5 itself uses,
imported rather than re-implemented, hard cuts included ACROSS scene
boundaries — D5 does not stop at a scene edge and neither does this):

    duration_s(shot_1)        = spoken(shot_1)                              [first in its run]
    duration_s(shot_i), i > 1 = spoken(shot_i) + shot_(i-1).transition_out.duration_s

Then, for any run: `compute_run_duration(run) == sum(spoken(shot) for shot
in run)` exactly (the added overlap terms cancel the ones D5 subtracts),
and hard cuts between runs cost nothing (D5's own guarantee) — so, summed
over the WHOLE timeline: `compute_timeline_duration(all_shots) ==
sum(spoken(shot) for every shot) == sum(scene narration durations)`, i.e.
the render's total duration equals the real total narration duration,
transitions and all, including transitions that straddle a scene boundary
(several real Shot Planner outputs put a fade on a scene's last shot —
see `tests/fixtures/m8_test_project.json`).

Proven with real numbers, including a gap-in-the-audio case, a dissolve
case, a hard-cut case, and a multi-scene cross-boundary-transition case, in
`tests/unit/timeline/test_narration_fit.py` — this docstring is the
derivation, that file is the proof.

## What this module refuses to guess at

A `narration_span` that runs past the end of its scene's alignment arrays,
a span that is empty or covers only whitespace, and a scene whose shots
don't exactly tile `narration_text` (gap, overlap, or short of the end) are
all data-integrity failures, not degraded-but-plausible inputs — this
module raises `PermanentError` rather than silently producing a number
that is wrong but looks fine. The Shot Planner's own output validator
already guarantees exact tiling for freshly-planned timelines (see
`app/planners/shot/planner.py`), so a violation here means corrupted or
hand-edited data, not a planner bug this module should paper over.

## F4 — a layer's timed entry lives at this same seam (2026-09-05)

`resolve_layer_entry_offsets` (bottom of this file) answers the identical
question one level in: `ShotLayer.enter_on_fragment` is a fragment INDEX,
never a time in seconds, for the same reason `narration_span` itself is a
character span rather than something the model predicts in seconds — a
model cannot predict a duration that does not exist yet, since narration
is measured AFTER planning. This module is where that duration first
becomes real, for a whole shot AND now, unconditionally CLAMPED so it can
never equal or exceed the shot's own (already-reconciled) duration, for
one layer within it — never a second place, and never at render time.

## F5 — a shot's own element reveal generalises the same arithmetic to a WINDOW (2026-09-05)

`resolve_element_reveals` (bottom of this file) is F4's identical
fragment-to-seconds idea, extended from a fragment-anchored POINT (a
layer's entry — "present from THIS moment on") to a fragment-anchored
WINDOW (a shot's own progressive reveal — "hidden until this moment,
fully revealed by that one"). Both anchors reuse the SAME "look up a
fragment's own character position in the real alignment, offset from
this shot's own onset" primitive (`_fragment_onset_offset_s`), plus one
new sibling for the window's far edge (`_fragment_finish_offset_s`,
using the fragment's own last character's END time rather than its
first character's START time) — one arithmetic idea shared by both
callers, not a second copy of it (R1). F5's own clamp
(`_clamp_reveal_window`) is correspondingly a WINDOW clamp: both the
start and the finish must land strictly inside the shot's own duration,
never merely the start.
"""

from dataclasses import dataclass

from app.core.errors import PermanentError
from app.core.logging import get_logger
from app.planners.fragments import NarrationFragment, split_narration_fragments
from app.schemas.timeline import Scene, Shot, Timeline
from app.timeline.duration import group_into_runs

logger = get_logger(__name__)

# F4 (illustrated_faceless.md, 2026-09-05): the minimum time a layer must
# remain on screen before its shot ends, once a fragment-derived entry is
# clamped into range (see `_clamp_entry_offset` below). Small on purpose -
# this is a floating-point/edge-case backstop, not a creative choice: by
# construction, `enter_on_fragment` is validated at plan time to fall
# within the OWNING SHOT's own fragment range (`_make_validator`'s
# `is_parallax` block, `app/planners/shot/planner.py`), so the fragment's
# own start time is already comfortably before this shot's own narration
# ends in the overwhelming majority of cases - this constant only matters
# when the entering fragment is the shot's very LAST one, where rounding
# could otherwise land the offset AT or past `duration_s`.
_ENTRY_MIN_TAIL_S = 0.05

# F5 (illustrated_faceless.md, 2026-09-05): same reasoning as
# `_ENTRY_MIN_TAIL_S` above (a floating-point/edge-case backstop, not a
# creative choice), kept as its own constant rather than reused because
# F5's ceiling has to leave room for a nonzero reveal DURATION on top of
# a single instant, not just a point.
_REVEAL_MIN_TAIL_S = 0.05
# The shortest a reveal window is allowed to shrink to when clamped -
# below this it would no longer read as a wipe, only a pop. Reasoned,
# not measured (no real reveal render exists yet, the same epistemic
# status `_LAYER_ENTRY_FADE_S`/`layer_entry_min_shot_gap` already
# carry): a wipe needs to visibly sweep across at least a few frames to
# read as motion rather than a cut, and this floor only ever bites in
# the rare case where the planner-chosen fragment window itself lands
# very close to the shot's own end (by construction, `reveal_start_
# fragment`/`reveal_end_fragment` are validated at plan time to fall
# inside the owning shot's own fragment range, so this is a backstop,
# not the ordinary path - the identical relationship `_ENTRY_MIN_TAIL_S`
# already has to F4's own entry).
_REVEAL_MIN_DURATION_S = 0.2


@dataclass(frozen=True)
class SceneAlignment:
    """One scene's ElevenLabs `alignment` object (never `normalized_
    alignment` — see `providers/elevenlabs.py`), decoded into the three
    parallel arrays `NarrationResult.alignment` carries. Indices correspond
    1:1 with the scene's own `narration_text`, which is what makes
    `Shot.narration_span` a direct index lookup into this with no
    alignment step of its own."""

    characters: list[str]
    character_start_times_seconds: list[float]
    character_end_times_seconds: list[float]

    @classmethod
    def from_raw(cls, alignment: dict) -> "SceneAlignment":
        try:
            return cls(
                characters=list(alignment["characters"]),
                character_start_times_seconds=list(alignment["character_start_times_seconds"]),
                character_end_times_seconds=list(alignment["character_end_times_seconds"]),
            )
        except KeyError as exc:
            raise PermanentError(f"malformed narration alignment, missing {exc}") from exc

    def __len__(self) -> int:
        return len(self.characters)


def _spoken_durations_for_scene(scene: Scene, alignment: SceneAlignment) -> dict[str, float]:
    """{shot_id: spoken duration} for one scene's shots — see module
    docstring for the boundary-based derivation and why it's used instead
    of a per-shot slice."""
    shots = sorted(scene.shots, key=lambda s: s.order)
    if not shots:
        raise PermanentError(f"scene {scene.id} has narration text but no shots to speak it")

    n = len(alignment)
    text_len = len(scene.narration_text)

    cursor = 0
    for shot in shots:
        if shot.narration_span is None:
            raise PermanentError(
                f"shot {shot.id} has no narration_span - cannot reconcile its duration "
                "against narration"
            )
        start, end = shot.narration_span
        if start != cursor:
            raise PermanentError(
                f"scene {scene.id}: shot {shot.id}'s narration_span starts at {start}, "
                f"expected {cursor} - shots must tile the scene's narration_text exactly, "
                "with no gap and no overlap between them"
            )
        if end <= start:
            raise PermanentError(f"shot {shot.id} has an empty narration_span {(start, end)}")
        if end > n:
            raise PermanentError(
                f"shot {shot.id}'s narration_span {(start, end)} runs past the end of its "
                f"scene's narration alignment ({n} characters)"
            )
        if not scene.narration_text[start:end].strip():
            raise PermanentError(
                f"shot {shot.id}'s narration_span {(start, end)} covers only whitespace - "
                "nothing is actually spoken, so it cannot be timed against narration"
            )
        cursor = end

    if cursor != text_len:
        raise PermanentError(
            f"scene {scene.id}: shots cover characters [0, {cursor}) but narration_text is "
            f"{text_len} characters long - some text is not covered by any shot"
        )
    if text_len != n:
        raise PermanentError(
            f"scene {scene.id}: narration_text is {text_len} characters but its synthesised "
            f"alignment covers {n} - the audio does not match the planned script"
        )

    scene_end_time = alignment.character_end_times_seconds[n - 1]
    durations: dict[str, float] = {}
    for index, shot in enumerate(shots):
        onset = alignment.character_start_times_seconds[shot.narration_span[0]]  # type: ignore[index]
        if index + 1 < len(shots):
            next_start = shots[index + 1].narration_span[0]  # type: ignore[index]
            offset = alignment.character_start_times_seconds[next_start]
        else:
            offset = scene_end_time
        duration = offset - onset
        if duration <= 0:
            raise PermanentError(
                f"shot {shot.id} reconciled to a non-positive duration ({duration}s) - its "
                "narration_span or the alignment timestamps are inconsistent"
            )
        durations[shot.id] = duration
    return durations


def reconcile_spoken_durations(
    scenes: list[Scene], alignments: dict[str, SceneAlignment]
) -> dict[str, float]:
    """{shot_id: spoken duration} across every scene, each independently
    reconciled against its own scene's alignment. Pure and total: raises
    `PermanentError` the moment any scene's data doesn't hold together,
    rather than returning a plausible-but-wrong number for the rest."""
    durations: dict[str, float] = {}
    for scene in scenes:
        alignment = alignments.get(scene.id)
        if alignment is None:
            raise PermanentError(f"no narration alignment supplied for scene {scene.id}")
        durations.update(_spoken_durations_for_scene(scene, alignment))
    return durations


def compensate_for_transitions(shots: list[Shot], spoken: dict[str, float]) -> dict[str, float]:
    """{shot_id: reconciled duration_s} — `spoken` inflated by each shot's
    incoming transition overlap so `compute_timeline_duration` (D5), which
    subtracts that same overlap once per transition, reproduces `spoken`'s
    total exactly. See module docstring for the derivation. Grouped into
    runs by `duration.group_into_runs` — the identical grouping D5 itself
    uses — over the FULL flat shot list, so a transition that straddles a
    scene boundary is compensated too."""
    reconciled: dict[str, float] = {}
    for run in group_into_runs(shots):
        previous: Shot | None = None
        for shot in run:
            base = spoken[shot.id]
            reconciled[shot.id] = (
                base if previous is None else base + previous.transition_out.duration_s
            )
            previous = shot
    return reconciled


def reconcile_timeline_durations(
    timeline: Timeline, alignments: dict[str, SceneAlignment]
) -> dict[str, float]:
    """The whole of step 2 in one call: {shot_id: new duration_s} for
    every shot in the timeline, ready to write back via `append_version`.
    Callers still recompute `metadata.total_duration_s` themselves via
    `compute_timeline_duration` (D5 arithmetic lives in exactly one place;
    this module reuses it, never re-derives it)."""
    spoken = reconcile_spoken_durations(timeline.scenes, alignments)
    return compensate_for_transitions(timeline.all_shots(), spoken)


def _fragment_onset_offset_s(
    fragments: list[NarrationFragment], fragment_index: int, alignment: SceneAlignment, onset: float
) -> float:
    """Seconds from a shot's own onset to the moment fragment number
    `fragment_index` (1-indexed) STARTS being spoken. Factored out of
    `resolve_layer_entry_offsets` (F4) so F5's `resolve_element_reveals`
    below shares the identical arithmetic rather than re-deriving it
    (R1) - both callers are asking the same question ("where, in real
    seconds relative to this shot, does this fragment's first character
    land") for two different creative decisions (a layer's entry point;
    a reveal's start)."""
    char_pos = fragments[fragment_index - 1].start
    return alignment.character_start_times_seconds[char_pos] - onset


def _fragment_finish_offset_s(
    fragments: list[NarrationFragment], fragment_index: int, alignment: SceneAlignment, onset: float
) -> float:
    """F5's own sibling to `_fragment_onset_offset_s` above: seconds from
    a shot's own onset to the moment fragment number `fragment_index`
    FINISHES being spoken - needed because a reveal must know when it
    COMPLETES, not merely when it starts (§2/F5), which a layer's entry
    never needed. Uses the fragment's own LAST character's END time, the
    same convention `_spoken_durations_for_scene` already uses for a
    scene's very last shot's own offset above."""
    char_pos = fragments[fragment_index - 1].end - 1
    return alignment.character_end_times_seconds[char_pos] - onset


def _clamp_entry_offset(raw_offset_s: float, *, duration_s: float, shot_id: str) -> float:
    """Clamp a fragment-derived layer entry strictly inside its shot - F4's
    own requirement: "an entry can never equal or exceed the shot's
    duration, and can never stretch narration" (D1). CLAMPED, never
    dropped: dropping would silently discard a planner-authored creative
    decision (F4 is deliberately a rare, specific dramatic move - see
    `illustrated_risograph.md`'s own rate cue - so silently losing one is
    a worse outcome than the reveal landing a beat later than planned) with
    no visible trace; clamping still plays the reveal, only compressed into
    whatever tail of the shot remains, and is logged so the compression is
    observable rather than silent. Lower-bounded at `0.0` (present from the
    very start) and upper-bounded at `duration_s - _ENTRY_MIN_TAIL_S` (or
    `0.0` if the shot is shorter than that tail) so the layer is never
    invisible for its entire shot."""
    lower = max(0.0, raw_offset_s)
    ceiling = max(0.0, duration_s - _ENTRY_MIN_TAIL_S)
    clamped = min(lower, ceiling)
    if abs(clamped - raw_offset_s) > 1e-6:
        logger.info(
            "narration_fit.layer_entry_clamped",
            extra={
                "shot_id": shot_id,
                "raw_offset_s": raw_offset_s,
                "clamped_offset_s": clamped,
                "shot_duration_s": duration_s,
            },
        )
    return clamped


def resolve_layer_entry_offsets(
    scenes: list[Scene],
    alignments: dict[str, SceneAlignment],
    reconciled_durations: dict[str, float],
) -> dict[str, list[float]]:
    """{shot_id: [each of `Shot.layers`' own resolved `enter_offset_s`, in
    `Shot.layers` order]} — F4 (illustrated_faceless.md §2/F4)'s own
    fragment-index-to-seconds derivation, at the SAME seam
    `reconcile_spoken_durations`/`compensate_for_transitions` above already
    fit `Shot.duration_s` to measured narration at (D1: narration is the
    master clock, picture — and now a layer's entry — is fitted to it,
    never the reverse). An entry anchored to a fragment INDEX rather than
    a time in seconds (the whole point of F4 -
    `app/planners/fragments.py`'s own thesis, applied one level in, to a
    layer) can only become a real second value once real character-level
    timestamps exist, exactly like `duration_s` itself — there is no
    earlier point in the pipeline where this arithmetic could run, and
    recording it here rather than at render time is what keeps
    `compute_render_fingerprint` honest (§4.1/R2) and closes the gap F2's
    own log named and left open: "layer drift was left a resolver concern,
    no resolver was written, and every drift shipped as 0.0".

    For each shot with at least one layer carrying `enter_on_fragment`:
    the entering fragment's own character START position (recomputed via
    `split_narration_fragments` on the scene's `narration_text` — pure and
    deterministic, I5; `Shot.narration_span` already depends on the
    identical "narration_text is unchanged since planning" assumption for
    this same reconciliation to mean anything at all, so this adds no new
    one) is looked up in the scene's real alignment, and the offset from
    THIS SHOT's own onset (the same `onset(shot)` `_spoken_durations_for_
    scene` above computes) is clamped into range by `_clamp_entry_offset`.

    A shot with no layers, or whose layers all have `enter_on_fragment is
    None` (present for the whole shot — the default and by far the common
    case, §3.1), is absent from the returned dict entirely, so a caller
    can tell "nothing to resolve" from "resolved to zero, on purpose" —
    and every project that never uses F4 touches this function for
    exactly zero shots."""
    offsets: dict[str, list[float]] = {}
    for scene in scenes:
        shots_with_entries = [
            shot
            for shot in scene.shots
            if any(layer.enter_on_fragment is not None for layer in shot.layers)
        ]
        if not shots_with_entries:
            continue

        alignment = alignments[scene.id]
        fragments = split_narration_fragments(scene.narration_text)

        for shot in shots_with_entries:
            assert shot.narration_span is not None  # already guaranteed for every planned shot
            onset = alignment.character_start_times_seconds[shot.narration_span[0]]
            duration = reconciled_durations[shot.id]
            shot_offsets: list[float] = []
            for layer in shot.layers:
                if layer.enter_on_fragment is None:
                    shot_offsets.append(0.0)
                    continue
                raw_offset = _fragment_onset_offset_s(
                    fragments, layer.enter_on_fragment, alignment, onset
                )
                shot_offsets.append(
                    _clamp_entry_offset(raw_offset, duration_s=duration, shot_id=shot.id)
                )
            offsets[shot.id] = shot_offsets
    return offsets


def _clamp_reveal_window(
    raw_start_s: float, raw_finish_s: float, *, duration_s: float, shot_id: str
) -> tuple[float, float]:
    """Clamp a fragment-derived reveal WINDOW so it both starts and
    FINISHES strictly inside its shot (§2/F5's own binding requirement -
    "a wipe still running when the shot cuts is worse than one that
    completes early"). Extends `_clamp_entry_offset`'s clamp-never-drop
    precedent from a single point to a window: never dropped, because
    dropping would silently discard a planner-authored creative decision
    with no visible trace (the same reasoning `_clamp_entry_offset`'s own
    docstring gives), and logged only when it actually changes something,
    so the compression is observable rather than silent.

    `start` is bounded into `[0.0, ceiling]` exactly like
    `_clamp_entry_offset`'s own single point. `finish` is then bounded
    into `[min(start + _REVEAL_MIN_DURATION_S, ceiling), ceiling]` - at
    least `_REVEAL_MIN_DURATION_S` after `start` whenever the shot has
    that much room left, otherwise pulled in to `ceiling` itself (a
    still-valid, if shorter-than-ideal, window; never inverted, never
    past the shot's own end)."""
    ceiling = max(0.0, duration_s - _REVEAL_MIN_TAIL_S)
    start = min(max(0.0, raw_start_s), ceiling)
    min_finish = min(start + _REVEAL_MIN_DURATION_S, ceiling)
    finish = min(max(raw_finish_s, min_finish), ceiling)
    if abs(start - raw_start_s) > 1e-6 or abs(finish - raw_finish_s) > 1e-6:
        logger.info(
            "narration_fit.element_reveal_clamped",
            extra={
                "shot_id": shot_id,
                "raw_start_s": raw_start_s,
                "raw_finish_s": raw_finish_s,
                "clamped_start_s": start,
                "clamped_finish_s": finish,
                "shot_duration_s": duration_s,
            },
        )
    return start, finish


def resolve_element_reveals(
    scenes: list[Scene],
    alignments: dict[str, SceneAlignment],
    reconciled_durations: dict[str, float],
) -> dict[str, tuple[float, float]]:
    """{shot_id: (reveal_start_offset_s, reveal_duration_s)} — F5
    (illustrated_faceless.md §2/F5)'s own fragment-window-to-seconds
    derivation, at the SAME seam `resolve_layer_entry_offsets` (F4)
    already reuses from `reconcile_spoken_durations`/`compensate_for_
    transitions` above. Generalises F4's single fragment-anchored POINT
    to a fragment-anchored WINDOW (`Shot.reveal_start_fragment` through
    `Shot.reveal_end_fragment`) using the SAME two primitives
    (`_fragment_onset_offset_s`/`_fragment_finish_offset_s`) rather than
    re-deriving the arithmetic a second time (R1) - both this function
    and F4's already answer "where, in real seconds relative to this
    shot, does fragment N's speech land", just at the window's two
    different edges.

    For each shot carrying a reveal (`reveal_direction is not None`,
    which `Shot._reveal_fields_are_all_or_nothing` already guarantees
    means both fragment numbers are set too): the start fragment's own
    character START position gives the raw window start, the end
    fragment's own character END position gives the raw window finish,
    both relative to THIS SHOT's own onset (the same `onset(shot)`
    `_spoken_durations_for_scene` computes), and `_clamp_reveal_window`
    bounds the pair strictly inside the shot's own (already-reconciled)
    duration.

    A shot with no reveal (`reveal_direction is None` - the default, and
    every shot that predates F5) is absent from the returned dict
    entirely, mirroring `resolve_layer_entry_offsets`'s own "nothing to
    resolve" contract exactly - a project that never uses F5 touches
    this function for zero shots."""
    windows: dict[str, tuple[float, float]] = {}
    for scene in scenes:
        shots_with_reveals = [shot for shot in scene.shots if shot.reveal_direction is not None]
        if not shots_with_reveals:
            continue

        alignment = alignments[scene.id]
        fragments = split_narration_fragments(scene.narration_text)

        for shot in shots_with_reveals:
            assert shot.narration_span is not None  # already guaranteed for every planned shot
            assert shot.reveal_start_fragment is not None
            assert shot.reveal_end_fragment is not None
            onset = alignment.character_start_times_seconds[shot.narration_span[0]]
            duration = reconciled_durations[shot.id]
            raw_start = _fragment_onset_offset_s(
                fragments, shot.reveal_start_fragment, alignment, onset
            )
            raw_finish = _fragment_finish_offset_s(
                fragments, shot.reveal_end_fragment, alignment, onset
            )
            start, finish = _clamp_reveal_window(
                raw_start, raw_finish, duration_s=duration, shot_id=shot.id
            )
            windows[shot.id] = (start, finish - start)
    return windows


def resolve_emphasis_cue_offsets(
    scenes: list[Scene],
    alignments: dict[str, SceneAlignment],
    reconciled_durations: dict[str, float],
) -> dict[str, float]:
    """{shot_id: offset_s} for each shot carrying an `EmphasisCue`.

    K2 (retention_fast_kinetic_text.md): the identical fragment-index-to-
    seconds derivation `resolve_layer_entry_offsets` (F4) already owns.
    `EmphasisCue.anchor_fragment` is a fragment INDEX, never a time in
    seconds — a planner cannot predict a duration that does not exist
    yet. This is the one seam where that index becomes real, relative to
    THIS SHOT's own onset, clamped by `_clamp_entry_offset` so a cue
    cannot equal or exceed the shot's own (already-reconciled) duration.

    A shot with no cue is absent from the returned dict entirely, so a
    project that never uses kinetic text touches this function for zero
    shots. A cue whose scene has no alignment yet is not this function's
    problem: it is only called from `NarrationStep` once alignments
    exist; until then `offset_s` stays at its schema default (0.0).
    """
    offsets: dict[str, float] = {}
    for scene in scenes:
        shots_with_cues = [shot for shot in scene.shots if shot.emphasis_cue is not None]
        if not shots_with_cues:
            continue

        alignment = alignments[scene.id]
        fragments = split_narration_fragments(scene.narration_text)

        for shot in shots_with_cues:
            assert shot.narration_span is not None
            assert shot.emphasis_cue is not None
            onset = alignment.character_start_times_seconds[shot.narration_span[0]]
            duration = reconciled_durations[shot.id]
            raw_offset = _fragment_onset_offset_s(
                fragments, shot.emphasis_cue.anchor_fragment, alignment, onset
            )
            offsets[shot.id] = _clamp_entry_offset(
                raw_offset, duration_s=duration, shot_id=shot.id
            )
    return offsets
