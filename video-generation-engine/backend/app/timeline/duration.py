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
