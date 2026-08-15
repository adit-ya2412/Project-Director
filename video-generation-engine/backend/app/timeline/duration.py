"""Transition/duration arithmetic — the one function (D5).

Transitions OVERLAP adjacent shots rather than extending the timeline: a
0.4s dissolve between two 3.0s shots yields 5.6s of video, not 6.0s. This
module is the single place that arithmetic lives. Both the Shot Planner
(M5) and the Renderer (M8) must call it — duplicating this logic anywhere
else is how audio and video quietly drift apart across a render.

A "run" is a maximal sequence of consecutive shots joined only by
non-hard-cut transitions (dissolve/fade). Hard cuts (transition type
`cut`, or any transition with `duration_s <= 0`) start a new run. Runs are
rendered independently (crossfaded internally) and then concatenated with
true zero-overlap hard cuts (implementation guide, Phase M8).
"""

from app.schemas.timeline import Shot, TransitionType


def _is_hard_cut(shot: Shot) -> bool:
    return shot.transition_out.type == TransitionType.CUT or shot.transition_out.duration_s <= 0.0


def group_into_runs(shots: list[Shot]) -> list[list[Shot]]:
    if not shots:
        return []

    runs: list[list[Shot]] = [[shots[0]]]
    for previous, current in zip(shots, shots[1:], strict=False):
        if _is_hard_cut(previous):
            runs.append([current])
        else:
            runs[-1].append(current)
    return runs


def compute_run_duration(run: list[Shot]) -> float:
    """Total on-screen duration of one run, accounting for internal
    crossfade overlaps."""
    if not run:
        return 0.0
    total = run[0].duration_s
    for previous, current in zip(run, run[1:], strict=False):
        overlap = previous.transition_out.duration_s
        total += current.duration_s - overlap
    return total


def compute_timeline_duration(shots: list[Shot]) -> float:
    """Total rendered duration across all shots, in order.

    Hard cuts between runs cost nothing; non-cut transitions within a run
    subtract their overlap exactly once. This must match
    `Timeline.metadata.total_duration_s` — planners set that field using
    this same function, never by hand.
    """
    return sum(compute_run_duration(run) for run in group_into_runs(shots))


def compute_shot_start_times(shots: list[Shot]) -> dict[str, float]:
    """Each shot's start time in seconds from the beginning of the
    rendered video (M9 — `GET /progress`, `starts_at_s`) — the offset a
    human would seek to in order to find that shot in the finished piece.

    Reuses the exact same run/overlap arithmetic `compute_timeline_duration`
    already uses (D5), rather than a naive running sum of `duration_s`,
    which would be wrong the moment any transition overlaps two shots:
    hard cuts between runs cost nothing, so a run's own start is exactly
    the sum of every previous run's `compute_run_duration`; within a run,
    shot i (i > 0) starts `overlap` seconds before the previous shot's own
    footage would otherwise have ended — the same crossfade math
    `compute_run_duration` sums up, just recorded per shot instead of
    only as a run total.
    """
    starts: dict[str, float] = {}
    elapsed = 0.0
    for run in group_into_runs(shots):
        cursor = elapsed
        starts[run[0].id] = cursor
        for previous, current in zip(run, run[1:], strict=False):
            cursor += previous.duration_s - previous.transition_out.duration_s
            starts[current.id] = cursor
        elapsed += compute_run_duration(run)
    return starts
