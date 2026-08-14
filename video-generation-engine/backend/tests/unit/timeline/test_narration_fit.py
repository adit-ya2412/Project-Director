"""Proves the derivation written out in `app/timeline/narration_fit.py`'s
module docstring: after reconciliation, (a) each shot's `duration_s`
matches its own real spoken slice (boundary-based, gap-safe), and (b)
`compute_timeline_duration` (D5) on the reconciled shots reproduces the
REAL total narration duration exactly - hard cuts, dissolves, an
inter-character pause, and a cross-scene transition all included. Pure,
no DB, no network.
"""

import pytest

from app.core.clock import utcnow
from app.core.errors import PermanentError
from app.schemas.timeline import (
    Scene,
    Shot,
    ShotIntent,
    Timeline,
    TimelineMetadata,
    Transition,
    TransitionType,
)
from app.timeline.duration import compute_timeline_duration
from app.timeline.narration_fit import (
    SceneAlignment,
    compensate_for_transitions,
    reconcile_spoken_durations,
    reconcile_timeline_durations,
)

# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _shot(
    shot_id: str,
    order: int,
    span: tuple[int, int],
    *,
    transition: TransitionType = TransitionType.CUT,
    transition_duration_s: float = 0.0,
) -> Shot:
    return Shot(
        id=shot_id,
        order=order,
        intent=ShotIntent.EXPLAIN,
        narration_span=span,
        duration_s=1.0,  # placeholder - overwritten by reconciliation
        transition_out=Transition(type=transition, duration_s=transition_duration_s),
    )


def _scene(scene_id: str, order: int, text: str, shots: list[Shot]) -> Scene:
    return Scene(
        id=scene_id,
        order=order,
        title=scene_id,
        narration_text=text,
        duration_s=sum(s.duration_s for s in shots),
        shots=shots,
    )


def _timeline(scenes: list[Scene]) -> Timeline:
    from app.schemas.timeline import ProducedBy

    return Timeline(
        timeline_id="t1",
        project_id="p1",
        version=3,
        produced_by=ProducedBy.SHOT_PLANNER,
        created_at=utcnow(),
        metadata=TimelineMetadata(),
        scenes=scenes,
    )


def _uniform_alignment(text: str, chars_per_second: float = 10.0) -> SceneAlignment:
    return SceneAlignment(
        characters=list(text),
        character_start_times_seconds=[i / chars_per_second for i in range(len(text))],
        character_end_times_seconds=[(i + 1) / chars_per_second for i in range(len(text))],
    )


# ---------------------------------------------------------------------------
# 1. The core derivation, with a deliberate gap (pause) at the shot boundary
# ---------------------------------------------------------------------------

# "Hello world" - 11 characters, indices 0..10. Shot 1 speaks "Hello"
# (indices 0-4), shot 2 speaks " world" (indices 5-10). Deliberately
# non-uniform timestamps, with a genuine 0.15s PAUSE between the end of
# character 4 ('o') and the start of character 5 (' ') - the exact
# scenario a naive `end[end-1] - start[start]` per-shot formula loses.
_TEXT = "Hello world"
_CHAR_START = [0.00, 0.10, 0.22, 0.30, 0.50, 0.75, 0.85, 1.00, 1.10, 1.25, 1.35]
_CHAR_END = [0.10, 0.22, 0.30, 0.50, 0.60, 0.85, 1.00, 1.10, 1.25, 1.35, 1.45]
_ALIGNMENT = SceneAlignment(
    characters=list(_TEXT),
    character_start_times_seconds=_CHAR_START,
    character_end_times_seconds=_CHAR_END,
)
_SCENE_TOTAL = _CHAR_END[-1] - _CHAR_START[0]  # 1.45 - 0.00 = 1.45


def test_boundary_based_spoken_durations_sum_exactly_to_the_scene_total():
    shot1 = _shot("sh1", 0, (0, 5))
    shot2 = _shot("sh2", 1, (5, 11))
    scene = _scene("sc1", 0, _TEXT, [shot1, shot2])

    spoken = reconcile_spoken_durations([scene], {"sc1": _ALIGNMENT})

    # shot1: onset(char 0)=0.00 to onset(char 5, the NEXT shot's first
    # char)=0.75 -> 0.75s. This deliberately absorbs the 0.15s pause
    # between char 4's end (0.60) and char 5's start (0.75): the pause is
    # attributed to shot1 (still on screen during it), not lost.
    assert spoken["sh1"] == pytest.approx(0.75)
    # shot2 (scene's last shot): onset(char 5)=0.75 to the scene's real
    # end time (1.45) -> 0.70s.
    assert spoken["sh2"] == pytest.approx(0.70)
    # The pair sums EXACTLY to the scene's total, pause included.
    assert spoken["sh1"] + spoken["sh2"] == pytest.approx(_SCENE_TOTAL)


def test_naive_per_shot_slice_formula_would_undercount_the_pause():
    """Documents exactly why `narration_fit` does NOT use
    `character_end_times_seconds[end-1] - character_start_times_seconds[start]`
    per shot: that formula is correct in isolation but drops the pause
    between shots entirely, under-stating the scene's real total."""
    naive_sh1 = _CHAR_END[4] - _CHAR_START[0]  # end of 'o' minus start of 'H'
    naive_sh2 = _CHAR_END[10] - _CHAR_START[5]  # end of last char minus start of ' '
    naive_total = naive_sh1 + naive_sh2

    assert naive_total == pytest.approx(1.30)
    assert naive_total < _SCENE_TOTAL  # loses exactly the 0.15s pause


def test_hard_cut_render_duration_equals_real_narration_total():
    shot1 = _shot("sh1", 0, (0, 5), transition=TransitionType.CUT, transition_duration_s=0.0)
    shot2 = _shot("sh2", 1, (5, 11))
    scene = _scene("sc1", 0, _TEXT, [shot1, shot2])
    timeline = _timeline([scene])

    reconciled = reconcile_timeline_durations(timeline, {"sc1": _ALIGNMENT})
    final_shots = [s.model_copy(update={"duration_s": reconciled[s.id]}) for s in [shot1, shot2]]

    assert compute_timeline_duration(final_shots) == pytest.approx(_SCENE_TOTAL)


def test_dissolve_transition_is_compensated_exactly():
    """A 0.3s dissolve between the two shots would, if `duration_s` were
    left as the raw spoken duration, shrink the rendered total by 0.3s
    (D5). Compensation must cancel that exactly."""
    shot1 = _shot("sh1", 0, (0, 5), transition=TransitionType.DISSOLVE, transition_duration_s=0.3)
    shot2 = _shot("sh2", 1, (5, 11))
    scene = _scene("sc1", 0, _TEXT, [shot1, shot2])
    timeline = _timeline([scene])

    reconciled = reconcile_timeline_durations(timeline, {"sc1": _ALIGNMENT})

    # shot1 (first in its run): untouched, still its raw spoken duration.
    assert reconciled["sh1"] == pytest.approx(0.75)
    # shot2: inflated by the incoming 0.3s overlap so D5's subtraction
    # cancels back out to its real spoken duration.
    assert reconciled["sh2"] == pytest.approx(0.70 + 0.3)

    final_shots = [s.model_copy(update={"duration_s": reconciled[s.id]}) for s in [shot1, shot2]]
    assert compute_timeline_duration(final_shots) == pytest.approx(_SCENE_TOTAL)


# ---------------------------------------------------------------------------
# 2. Multi-scene, with a transition that straddles the scene boundary
# ---------------------------------------------------------------------------


def test_multi_scene_cross_boundary_transition_still_sums_exactly():
    """Real Shot Planner output puts fades/dissolves on a scene's LAST
    shot that visually run into the next scene's FIRST shot (see
    tests/fixtures/m8_test_project.json) - `compute_timeline_duration`
    doesn't stop at scene boundaries, and neither does compensation."""
    text_a = "Coal built the factories."
    text_b = "Oil they did not have."
    alignment_a = _uniform_alignment(text_a, chars_per_second=12.0)
    alignment_b = _uniform_alignment(text_b, chars_per_second=8.0)

    a1 = _shot("a1", 0, (0, 10), transition=TransitionType.CUT, transition_duration_s=0.0)
    a2 = _shot(
        "a2",
        1,
        (10, len(text_a)),
        transition=TransitionType.FADE,
        transition_duration_s=0.5,  # straddles into scene B
    )
    b1 = _shot("b1", 0, (0, 8), transition=TransitionType.CUT, transition_duration_s=0.0)
    b2 = _shot("b2", 1, (8, len(text_b)))
    scene_a = _scene("sc_a", 0, text_a, [a1, a2])
    scene_b = _scene("sc_b", 1, text_b, [b1, b2])
    timeline = _timeline([scene_a, scene_b])

    reconciled = reconcile_timeline_durations(timeline, {"sc_a": alignment_a, "sc_b": alignment_b})
    all_shots = [a1, a2, b1, b2]
    final_shots = [s.model_copy(update={"duration_s": reconciled[s.id]}) for s in all_shots]

    total_a = (
        alignment_a.character_end_times_seconds[-1] - alignment_a.character_start_times_seconds[0]
    )
    total_b = (
        alignment_b.character_end_times_seconds[-1] - alignment_b.character_start_times_seconds[0]
    )

    assert compute_timeline_duration(final_shots) == pytest.approx(total_a + total_b)


# ---------------------------------------------------------------------------
# 3. Honest failure, not a plausible-but-wrong number
# ---------------------------------------------------------------------------


def test_missing_narration_span_fails_loudly():
    shot = Shot(id="sh1", order=0, intent=ShotIntent.EXPLAIN, duration_s=1.0, narration_span=None)
    scene = _scene("sc1", 0, "hello", [shot])
    with pytest.raises(PermanentError, match="no narration_span"):
        reconcile_spoken_durations([scene], {"sc1": _uniform_alignment("hello")})


def test_span_past_end_of_alignment_fails_loudly():
    shot = _shot("sh1", 0, (0, 20))  # text is only 11 chars, alignment matches
    scene = _scene("sc1", 0, _TEXT, [shot])
    with pytest.raises(PermanentError, match="runs past the end"):
        reconcile_spoken_durations([scene], {"sc1": _ALIGNMENT})


def test_empty_span_fails_loudly():
    shot = _shot("sh1", 0, (0, 0))  # starts exactly at cursor, so the gap
    # check passes and the emptiness check is the one that fires.
    scene = _scene("sc1", 0, _TEXT, [shot])
    with pytest.raises(PermanentError, match="empty narration_span"):
        reconcile_spoken_durations([scene], {"sc1": _ALIGNMENT})


def test_whitespace_only_span_fails_loudly():
    # "Hello world" index 5 is a single space.
    shot1 = _shot("sh1", 0, (0, 5))
    shot2 = _shot("sh2", 1, (5, 6))  # just the space
    shot3 = _shot("sh3", 2, (6, 11))
    scene = _scene("sc1", 0, _TEXT, [shot1, shot2, shot3])
    with pytest.raises(PermanentError, match="only whitespace"):
        reconcile_spoken_durations([scene], {"sc1": _ALIGNMENT})


def test_gap_between_shots_fails_loudly():
    shot1 = _shot("sh1", 0, (0, 4))  # ends one character early
    shot2 = _shot("sh2", 1, (5, 11))
    scene = _scene("sc1", 0, _TEXT, [shot1, shot2])
    with pytest.raises(PermanentError, match="expected 4"):
        reconcile_spoken_durations([scene], {"sc1": _ALIGNMENT})


def test_shots_not_covering_the_whole_text_fails_loudly():
    shot1 = _shot("sh1", 0, (0, 5))
    scene = _scene("sc1", 0, _TEXT, [shot1])  # only covers "Hello", not " world"
    with pytest.raises(PermanentError, match="not covered by any shot"):
        reconcile_spoken_durations([scene], {"sc1": _ALIGNMENT})


def test_alignment_length_mismatch_with_narration_text_fails_loudly():
    # Longer than the narration text, not shorter: a shorter alignment
    # would trip the "runs past the end" check first (also correct, but
    # a different failure) since a span's end would then exceed the
    # alignment's length before the two totals are even compared.
    shot1 = _shot("sh1", 0, (0, 5))
    shot2 = _shot("sh2", 1, (5, 11))
    scene = _scene("sc1", 0, _TEXT, [shot1, shot2])
    long_alignment = _uniform_alignment(_TEXT + "!!")
    with pytest.raises(PermanentError, match="does not match the planned script"):
        reconcile_spoken_durations([scene], {"sc1": long_alignment})


def test_missing_scene_alignment_fails_loudly():
    shot = _shot("sh1", 0, (0, 11))
    scene = _scene("sc1", 0, _TEXT, [shot])
    with pytest.raises(PermanentError, match="no narration alignment"):
        reconcile_spoken_durations([scene], {})


def test_scene_with_no_shots_fails_loudly():
    scene = _scene("sc1", 0, _TEXT, [])
    with pytest.raises(PermanentError, match="no shots"):
        reconcile_spoken_durations([scene], {"sc1": _ALIGNMENT})


def test_non_positive_reconciled_duration_fails_loudly():
    # Two adjacent characters sharing the identical start timestamp makes
    # a zero-length window for the shot ending there.
    starts = list(_CHAR_START)
    starts[5] = starts[0]  # shot1's onset == shot2's onset -> shot1 spans zero time
    broken_alignment = SceneAlignment(
        characters=list(_TEXT),
        character_start_times_seconds=starts,
        character_end_times_seconds=_CHAR_END,
    )
    shot1 = _shot("sh1", 0, (0, 5))
    shot2 = _shot("sh2", 1, (5, 11))
    scene = _scene("sc1", 0, _TEXT, [shot1, shot2])
    with pytest.raises(PermanentError, match="non-positive duration"):
        reconcile_spoken_durations([scene], {"sc1": broken_alignment})


# ---------------------------------------------------------------------------
# 4. compensate_for_transitions in isolation
# ---------------------------------------------------------------------------


def test_compensate_for_transitions_leaves_hard_cut_runs_untouched():
    shot1 = _shot("sh1", 0, (0, 5))
    shot2 = _shot("sh2", 1, (5, 11))
    reconciled = compensate_for_transitions([shot1, shot2], {"sh1": 1.0, "sh2": 2.0})
    assert reconciled == {"sh1": 1.0, "sh2": 2.0}


def test_compensate_for_transitions_inflates_only_the_follower():
    shot1 = _shot("sh1", 0, (0, 5), transition=TransitionType.DISSOLVE, transition_duration_s=0.4)
    shot2 = _shot("sh2", 1, (5, 11))
    reconciled = compensate_for_transitions([shot1, shot2], {"sh1": 1.0, "sh2": 2.0})
    assert reconciled == {"sh1": 1.0, "sh2": 2.4}
