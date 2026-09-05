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
    Camera,
    CameraMovement,
    LayerRole,
    RevealDirection,
    Scene,
    Shot,
    ShotIntent,
    ShotLayer,
    Timeline,
    TimelineMetadata,
    Transition,
    TransitionType,
)
from app.timeline.duration import compute_timeline_duration
from app.timeline.narration_fit import (
    SceneAlignment,
    _clamp_entry_offset,
    _clamp_reveal_window,
    compensate_for_transitions,
    reconcile_spoken_durations,
    reconcile_timeline_durations,
    resolve_element_reveals,
    resolve_layer_entry_offsets,
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


# ---------------------------------------------------------------------------
# 5. F4 - `resolve_layer_entry_offsets` (illustrated_faceless.md §2/F4):
# a layer's fragment-anchored entry, turned into real seconds at the SAME
# seam `duration_s` itself is fitted to narration at.
# ---------------------------------------------------------------------------

# "Coal built the factories. Steel followed close behind." - two
# sentences, so `split_narration_fragments` produces exactly two
# fragments: 1 = [0, 26) "Coal built the factories.", 2 = [26, 54) "Steel
# followed close behind." (confirmed directly against the real splitter,
# not assumed by hand).
_F4_TEXT = "Coal built the factories. Steel followed close behind."


def _layered_shot(shot_id: str, order: int, span: tuple[int, int], *, entry: int | None) -> Shot:
    return Shot(
        id=shot_id,
        order=order,
        intent=ShotIntent.EXPLAIN,
        narration_span=span,
        duration_s=1.0,  # placeholder - overwritten by reconciliation
        layers=[
            ShotLayer(role=LayerRole.BACKGROUND, prompt="a mill"),
            ShotLayer(role=LayerRole.SUBJECT, prompt="a worker", enter_on_fragment=entry),
        ],
    )


def test_entry_resolves_to_the_fragments_own_start_time_relative_to_the_shot():
    shot = _layered_shot("sh1", 0, (0, len(_F4_TEXT)), entry=2)
    scene = _scene("sc1", 0, _F4_TEXT, [shot])
    alignment = _uniform_alignment(_F4_TEXT, chars_per_second=10.0)

    reconciled = reconcile_timeline_durations(_timeline([scene]), {"sc1": alignment})
    offsets = resolve_layer_entry_offsets([scene], {"sc1": alignment}, reconciled)

    # Fragment 2 starts at character 26 -> onset 2.6s. The shot's own
    # onset is character 0 -> 0.0s. So the reveal lands at 2.6s into the
    # shot - the exact moment narration reaches "Steel".
    background_offset, subject_offset = offsets["sh1"]
    assert background_offset == 0.0
    assert subject_offset == pytest.approx(2.6)


def test_a_shot_with_no_entry_is_absent_from_the_result():
    """Present for the whole shot (the default, and the common case even
    among parallax shots, §3.1) means NOTHING to resolve - the shot is
    absent from the dict entirely, not merely present with a `0.0` list."""
    shot = _layered_shot("sh1", 0, (0, len(_F4_TEXT)), entry=None)
    scene = _scene("sc1", 0, _F4_TEXT, [shot])
    alignment = _uniform_alignment(_F4_TEXT, chars_per_second=10.0)

    reconciled = reconcile_timeline_durations(_timeline([scene]), {"sc1": alignment})
    offsets = resolve_layer_entry_offsets([scene], {"sc1": alignment}, reconciled)

    assert offsets == {}


def test_a_shot_with_no_layers_at_all_is_untouched():
    shot = _shot("sh1", 0, (0, len(_F4_TEXT)))  # the plain builder - layers=[]
    scene = _scene("sc1", 0, _F4_TEXT, [shot])
    alignment = _uniform_alignment(_F4_TEXT, chars_per_second=10.0)

    reconciled = reconcile_timeline_durations(_timeline([scene]), {"sc1": alignment})
    assert resolve_layer_entry_offsets([scene], {"sc1": alignment}, reconciled) == {}


def test_the_clamp_keeps_the_entry_strictly_inside_the_shot():
    """A contrived (non-uniform) alignment where the entering fragment's
    own start time sits closer to the scene's real end than F4's own
    minimum tail (`_ENTRY_MIN_TAIL_S`) allows - the arithmetic that would
    otherwise land the entry AT (or past) the shot's own duration is
    clamped back inside it, never dropped (see `_clamp_entry_offset`'s own
    docstring for why clamp rather than drop)."""
    text = "Ab. C."  # fragment 2 = [4, 6), "C."
    starts = [0.00, 0.10, 0.20, 0.30, 0.97, 0.99]
    ends = [0.10, 0.20, 0.30, 0.40, 0.99, 1.00]
    alignment = SceneAlignment(
        characters=list(text),
        character_start_times_seconds=starts,
        character_end_times_seconds=ends,
    )
    shot = _layered_shot("sh1", 0, (0, len(text)), entry=2)
    scene = _scene("sc1", 0, text, [shot])

    reconciled = reconcile_timeline_durations(_timeline([scene]), {"sc1": alignment})
    assert reconciled["sh1"] == pytest.approx(1.00)  # the shot's own final duration

    offsets = resolve_layer_entry_offsets([scene], {"sc1": alignment}, reconciled)
    _, subject_offset = offsets["sh1"]

    # Raw arithmetic would put the entry at 0.97s into a 1.00s shot - only
    # 0.03s of visible layer left. Clamped to leave at least
    # `_ENTRY_MIN_TAIL_S` (0.05s) of tail instead.
    assert subject_offset < reconciled["sh1"]
    assert subject_offset == pytest.approx(0.95)


def test_clamp_entry_offset_passes_a_value_already_in_range_unchanged():
    assert _clamp_entry_offset(1.0, duration_s=5.0, shot_id="sh1") == pytest.approx(1.0)


def test_clamp_entry_offset_never_reaches_or_exceeds_duration():
    clamped = _clamp_entry_offset(10.0, duration_s=2.0, shot_id="sh1")
    assert clamped < 2.0
    assert clamped == pytest.approx(2.0 - 0.05)


def test_clamp_entry_offset_never_goes_negative():
    assert _clamp_entry_offset(-1.0, duration_s=5.0, shot_id="sh1") == 0.0


def test_clamp_entry_offset_on_a_shot_shorter_than_the_tail_clamps_to_zero():
    assert _clamp_entry_offset(0.5, duration_s=0.02, shot_id="sh1") == 0.0


def test_clamp_logs_only_when_it_actually_changes_the_value(caplog):
    with caplog.at_level("INFO"):
        _clamp_entry_offset(1.0, duration_s=5.0, shot_id="sh1")
    assert not any(r.message == "narration_fit.layer_entry_clamped" for r in caplog.records)

    caplog.clear()
    with caplog.at_level("INFO"):
        _clamp_entry_offset(10.0, duration_s=2.0, shot_id="sh1")
    records = [r for r in caplog.records if r.message == "narration_fit.layer_entry_clamped"]
    assert len(records) == 1
    assert records[0].shot_id == "sh1"


# ---------------------------------------------------------------------------
# 6. F5 - `resolve_element_reveals` (illustrated_faceless.md §2/F5): a shot's
# own reveal WINDOW (start fragment through end fragment), turned into real
# seconds at the SAME seam - generalised from F4's single fragment-anchored
# POINT above.
# ---------------------------------------------------------------------------


def _reveal_shot(
    shot_id: str,
    order: int,
    span: tuple[int, int],
    *,
    start_fragment: int | None,
    end_fragment: int | None,
) -> Shot:
    direction = None if start_fragment is None else RevealDirection.BOTTOM_TO_TOP
    return Shot(
        id=shot_id,
        order=order,
        intent=ShotIntent.EXPLAIN,
        narration_span=span,
        duration_s=1.0,  # placeholder - overwritten by reconciliation
        camera=Camera(movement=CameraMovement.STATIC),
        reveal_direction=direction,
        reveal_start_fragment=start_fragment,
        reveal_end_fragment=end_fragment,
    )


def test_reveal_resolves_to_the_fragment_windows_start_and_finish_relative_to_the_shot():
    """The ordinary, unclamped case: a reveal window that covers only
    fragment 1 (NOT the shot's own last fragment), so neither edge is
    anywhere near the shot's own duration ceiling."""
    shot = _reveal_shot("sh1", 0, (0, len(_F4_TEXT)), start_fragment=1, end_fragment=1)
    scene = _scene("sc1", 0, _F4_TEXT, [shot])
    alignment = _uniform_alignment(_F4_TEXT, chars_per_second=10.0)

    reconciled = reconcile_timeline_durations(_timeline([scene]), {"sc1": alignment})
    windows = resolve_element_reveals([scene], {"sc1": alignment}, reconciled)

    # Fragment 1 spans characters [0, 26): starts at 0.0s, its own last
    # character (index 25) ends at 2.6s. The shot's own onset is 0.0s, so
    # the window is [0.0, 2.6) - a 2.6s reveal landing well inside the
    # shot's own 5.4s duration.
    start_offset_s, duration_s = windows["sh1"]
    assert start_offset_s == pytest.approx(0.0)
    assert duration_s == pytest.approx(2.6)


def test_reveal_resolves_relative_to_a_non_zero_shot_onset():
    """A reveal on the SECOND shot of a scene must be relative to THAT
    shot's own onset, not the scene's - the identical property F4's own
    entry resolution already proves for `resolve_layer_entry_offsets`."""
    shot1 = _shot("sh1", 0, (0, 26))
    shot2 = _reveal_shot("sh2", 1, (26, 54), start_fragment=2, end_fragment=2)
    scene = _scene("sc1", 0, _F4_TEXT, [shot1, shot2])
    alignment = _uniform_alignment(_F4_TEXT, chars_per_second=10.0)

    reconciled = reconcile_timeline_durations(_timeline([scene]), {"sc1": alignment})
    windows = resolve_element_reveals([scene], {"sc1": alignment}, reconciled)

    assert "sh1" not in windows  # no reveal on shot1
    start_offset_s, duration_s = windows["sh2"]
    # shot2's own onset is 2.6s (character 26). Fragment 2 IS shot2's
    # entire narration, so the raw window is [2.6, 5.4) relative to the
    # scene, i.e. [0.0, 2.8) relative to shot2's own onset - which is
    # shot2's own full reconciled duration, so the trailing-tail clamp
    # (`_REVEAL_MIN_TAIL_S`) trims a hair off the finish (see the
    # dedicated clamp tests below for why this is the expected, routine
    # outcome whenever a reveal's own end fragment IS the shot's last).
    assert reconciled["sh2"] == pytest.approx(2.8)
    assert start_offset_s == pytest.approx(0.0)
    assert duration_s == pytest.approx(2.8 - 0.05)


def test_a_shot_with_no_reveal_is_absent_from_the_result():
    shot = _reveal_shot("sh1", 0, (0, len(_F4_TEXT)), start_fragment=None, end_fragment=None)
    scene = _scene("sc1", 0, _F4_TEXT, [shot])
    alignment = _uniform_alignment(_F4_TEXT, chars_per_second=10.0)

    reconciled = reconcile_timeline_durations(_timeline([scene]), {"sc1": alignment})
    assert resolve_element_reveals([scene], {"sc1": alignment}, reconciled) == {}


def test_a_scene_with_no_reveals_at_all_is_untouched():
    shot = _shot("sh1", 0, (0, len(_F4_TEXT)))  # the plain builder - no reveal fields
    scene = _scene("sc1", 0, _F4_TEXT, [shot])
    alignment = _uniform_alignment(_F4_TEXT, chars_per_second=10.0)

    reconciled = reconcile_timeline_durations(_timeline([scene]), {"sc1": alignment})
    assert resolve_element_reveals([scene], {"sc1": alignment}, reconciled) == {}


def test_the_clamp_keeps_the_reveal_window_strictly_inside_the_shot_in_context():
    """Same contrived (non-uniform) alignment as F4's own clamp test - a
    reveal window whose raw finish lands exactly AT the shot's own
    duration is pulled back inside it, never dropped."""
    text = "Ab. C."  # fragment 1 = [0, 4), fragment 2 = [4, 6)
    starts = [0.00, 0.10, 0.20, 0.30, 0.97, 0.99]
    ends = [0.10, 0.20, 0.30, 0.40, 0.99, 1.00]
    alignment = SceneAlignment(
        characters=list(text),
        character_start_times_seconds=starts,
        character_end_times_seconds=ends,
    )
    shot = _reveal_shot("sh1", 0, (0, len(text)), start_fragment=1, end_fragment=2)
    scene = _scene("sc1", 0, text, [shot])

    reconciled = reconcile_timeline_durations(_timeline([scene]), {"sc1": alignment})
    assert reconciled["sh1"] == pytest.approx(1.00)

    windows = resolve_element_reveals([scene], {"sc1": alignment}, reconciled)
    start_offset_s, duration_s = windows["sh1"]

    # Raw arithmetic would put the finish exactly at 1.00s into a 1.00s
    # shot. Clamped so it finishes strictly inside, leaving at least
    # `_REVEAL_MIN_TAIL_S` (0.05s).
    assert start_offset_s == pytest.approx(0.0)
    assert start_offset_s + duration_s < reconciled["sh1"]
    assert start_offset_s + duration_s == pytest.approx(0.95)


# -- `_clamp_reveal_window` in isolation ---------------------------------


def test_clamp_reveal_window_passes_a_window_already_in_range_unchanged():
    start, finish = _clamp_reveal_window(1.0, 2.0, duration_s=5.0, shot_id="sh1")
    assert start == pytest.approx(1.0)
    assert finish == pytest.approx(2.0)


def test_clamp_reveal_window_never_lets_finish_reach_or_exceed_duration():
    start, finish = _clamp_reveal_window(0.0, 10.0, duration_s=2.0, shot_id="sh1")
    assert finish < 2.0
    assert finish == pytest.approx(2.0 - 0.05)
    assert start == pytest.approx(0.0)


def test_clamp_reveal_window_never_lets_start_go_negative():
    start, _finish = _clamp_reveal_window(-1.0, 1.0, duration_s=5.0, shot_id="sh1")
    assert start == 0.0


def test_clamp_reveal_window_extends_a_too_short_raw_window_up_to_the_minimum():
    """The opposite direction from a compression clamp: a raw window
    narrower than `_REVEAL_MIN_DURATION_S` (0.2s) is widened, not shrunk
    further, whenever the shot has the room - a reveal that would
    otherwise be too fast to read as a wipe still gets a floor."""
    start, finish = _clamp_reveal_window(1.0, 1.05, duration_s=5.0, shot_id="sh1")
    assert start == pytest.approx(1.0)
    assert finish == pytest.approx(1.2)


def test_clamp_reveal_window_on_a_shot_shorter_than_the_tail_clamps_both_to_zero():
    start, finish = _clamp_reveal_window(0.5, 0.6, duration_s=0.02, shot_id="sh1")
    assert start == 0.0
    assert finish == 0.0


def test_clamp_reveal_window_logs_only_when_it_actually_changes_something(caplog):
    with caplog.at_level("INFO"):
        _clamp_reveal_window(1.0, 2.0, duration_s=5.0, shot_id="sh1")
    assert not any(r.message == "narration_fit.element_reveal_clamped" for r in caplog.records)

    caplog.clear()
    with caplog.at_level("INFO"):
        _clamp_reveal_window(0.0, 10.0, duration_s=2.0, shot_id="sh1")
    records = [r for r in caplog.records if r.message == "narration_fit.element_reveal_clamped"]
    assert len(records) == 1
    assert records[0].shot_id == "sh1"
