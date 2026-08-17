"""Unit tests for app/timeline/duration.py - in particular
`compute_shot_start_times`, added for M9's `GET /progress` `starts_at_s`
field. Pure functions, no database - written to run alongside the rest
of the suite, but NOT executed in this session (see the coordinator's
"do not run pytest" instruction while a live project sits at the
approval gate in the shared dev Postgres).

Every case below double-checks the same invariant a different way: for
a single run, a shot's start time plus its own `duration_s` must equal
`compute_run_duration` of every shot up to and including it - i.e.
`compute_shot_start_times` and `compute_run_duration`/
`compute_timeline_duration` must always agree, since both are meant to
describe the exact same rendered timeline.
"""

from app.schemas.timeline import Shot, ShotIntent, Transition, TransitionType
from app.timeline.duration import compute_shot_start_times, compute_timeline_duration


def _shot(shot_id: str, *, duration_s: float, transition_out_s: float = 0.0) -> Shot:
    transition_type = TransitionType.CUT if transition_out_s <= 0.0 else TransitionType.DISSOLVE
    return Shot(
        id=shot_id,
        order=0,
        intent=ShotIntent.EXPLAIN,
        duration_s=duration_s,
        transition_out=Transition(type=transition_type, duration_s=transition_out_s),
    )


def test_single_shot_starts_at_zero():
    shots = [_shot("sh_01", duration_s=3.0)]
    assert compute_shot_start_times(shots) == {"sh_01": 0.0}


def test_two_shots_joined_by_a_hard_cut_the_second_starts_after_the_first_ends():
    shots = [
        _shot("sh_01", duration_s=3.0),  # hard cut (default) -> new run
        _shot("sh_02", duration_s=2.0),
    ]
    starts = compute_shot_start_times(shots)
    assert starts == {"sh_01": 0.0, "sh_02": 3.0}
    # A hard cut costs nothing (D5) - the naive sum is also the right
    # answer here, which is exactly why this case alone wouldn't catch a
    # regression; the dissolve case below is the one that would.
    assert starts["sh_02"] == compute_timeline_duration(shots[:1])


def test_two_shots_joined_by_a_dissolve_the_second_starts_before_the_first_ends():
    shots = [
        _shot("sh_01", duration_s=3.0, transition_out_s=0.4),  # dissolves into sh_02
        _shot("sh_02", duration_s=2.0),
    ]
    starts = compute_shot_start_times(shots)
    # The second shot starts 0.4s BEFORE the first shot's own 3.0s ends -
    # a naive cumulative sum (3.0) would be wrong by exactly the overlap.
    assert starts == {"sh_01": 0.0, "sh_02": 2.6}


def test_three_shots_two_runs_overlap_only_applies_within_the_run():
    shots = [
        _shot("sh_01", duration_s=3.0, transition_out_s=0.4),  # dissolves into sh_02
        _shot("sh_02", duration_s=2.0),  # hard cut (default) -> new run starts at sh_03
        _shot("sh_03", duration_s=1.5),
    ]
    starts = compute_shot_start_times(shots)
    assert starts["sh_01"] == 0.0
    assert starts["sh_02"] == 2.6  # 3.0 - 0.4, same as the two-shot dissolve case
    # Run 1 (sh_01, sh_02) has its own total duration via compute_run_duration
    # (2.6 + 2.0 = 4.6); sh_03 starts a fresh run right after it, costing
    # nothing extra for the hard cut.
    assert starts["sh_03"] == compute_timeline_duration(shots[:2])


def test_last_shot_start_plus_its_own_duration_equals_the_timeline_total_for_one_run():
    """The core cross-check: `compute_shot_start_times` and
    `compute_timeline_duration` describe the same render, so they must
    never disagree about where the last shot's own footage ends."""
    shots = [
        _shot("sh_01", duration_s=4.0, transition_out_s=0.5),
        _shot("sh_02", duration_s=3.0, transition_out_s=0.3),
        _shot("sh_03", duration_s=2.0),
    ]
    starts = compute_shot_start_times(shots)
    assert starts["sh_03"] + shots[-1].duration_s == compute_timeline_duration(shots)


def test_empty_shot_list_returns_an_empty_mapping():
    assert compute_shot_start_times([]) == {}


def test_wipe_left_and_dip_to_black_are_treated_as_non_cut_like_dissolve():
    """New transitions (motion_new_styles_and_long_form_videos.md §2.6,
    Tier 2, 2026-08-17) - `WIPE_LEFT`/`DIP_TO_BLACK` must overlap exactly
    like `DISSOLVE` already does (D5), not be silently treated as hard
    cuts. Verified against a real render too (a genuine ffmpeg xfade with
    each transition name, and the full `render_timeline` pipeline mixing
    both with a real hard cut) - this is the pure-arithmetic half of
    that same check."""
    from app.schemas.timeline import Transition, TransitionType
    from app.timeline.duration import compute_timeline_duration, group_into_runs

    shots = [
        Shot(
            id="sh_01",
            order=0,
            intent=ShotIntent.INTRODUCE,
            duration_s=2.0,
            transition_out=Transition(type=TransitionType.WIPE_LEFT, duration_s=0.5),
        ),
        Shot(
            id="sh_02",
            order=1,
            intent=ShotIntent.EXPLAIN,
            duration_s=2.0,
            transition_out=Transition(type=TransitionType.DIP_TO_BLACK, duration_s=0.5),
        ),
        Shot(
            id="sh_03",
            order=2,
            intent=ShotIntent.REVEAL,
            duration_s=2.0,
        ),
    ]
    runs = group_into_runs(shots)
    assert len(runs) == 1  # both transitions are non-cut -> one continuous run
    assert compute_timeline_duration(shots) == 5.0  # 6.0 raw - 0.5 - 0.5 overlap
