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
"""

from dataclasses import dataclass

from app.core.errors import PermanentError
from app.core.logging import get_logger
from app.planners.fragments import split_narration_fragments
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
                char_pos = fragments[layer.enter_on_fragment - 1].start
                raw_offset = alignment.character_start_times_seconds[char_pos] - onset
                shot_offsets.append(
                    _clamp_entry_offset(raw_offset, duration_s=duration, shot_id=shot.id)
                )
            offsets[shot.id] = shot_offsets
    return offsets
