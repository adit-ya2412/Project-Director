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
"""

from dataclasses import dataclass

from app.core.errors import PermanentError
from app.schemas.timeline import Scene, Shot, Timeline
from app.timeline.duration import group_into_runs


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
