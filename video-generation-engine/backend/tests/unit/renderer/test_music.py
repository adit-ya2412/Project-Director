"""`app/renderer/music.py` - pure gain arithmetic / duck intervals, no ffmpeg.

Covers analysis.md RV6: the BGM upload slider's `gain_offset_db` used to
be applied to the bed gain only (`render.py`'s `mux_music` call), while
`_volume_chain` below computes `relative_duck = duck_linear / bed_linear`
on top of an unconditional `volume=bed_linear` - which makes the level
during a narration window resolve to the ABSOLUTE `duck_gain_db`,
independent of the bed. Offsetting the bed alone therefore did not move
the ducked floor; once the offset dropped the bed below the duck gain,
`relative_duck` exceeded 1.0 and ducking INVERTED (music got louder, not
quieter, under narration). `test_music_gain_offset_changes_the_fingerprint`
(test_fingerprint.py) only proved the fingerprint moved - nothing
exercised the bed/duck interaction, so the inversion shipped with every
test passing (the same shape as RV5: a new input got a fingerprint test
but not a behaviour test).

OQ-1b: speaking intervals from alignment (merge threshold, concat clock)
and stepped duck ramps.
"""

import math

import pytest

from app.renderer.captions import MIN_CUE_DURATION_S
from app.renderer.music import (
    DUCK_CHAR_PAUSE_S,
    DUCK_MERGE_THRESHOLD_S,
    DUCK_RAMP_S,
    DUCK_RAMP_STEPS,
    _db_to_linear,
    _merge_touching_intervals,
    _volume_chain,
    combine_duck_windows,
    duck_envelope_content_hash,
    duck_ramp_windows,
    duck_ramp_windows_segments,
    offset_bed_and_duck_gain_db,
    speaking_intervals_from_alignment,
)
from app.script.styles import resolve_music_gains

# The three real style mixes this bug affected (styles.py / RV6's table).
_STYLES = ["retention_fast", "documentary_archival", "stillness"]

# The BGM upload endpoint bounds the slider to this range
# (`POST /projects/{id}/music/upload`, analysis.md decision 7).
_OFFSETS = [-40.0, -20.0, -10.0, -6.0, -4.0, 0.0, 12.0, 24.0]


def test_gain_offset_never_inverts_ducking():
    """RV6 regression: for every real style's bed/duck pair and every
    slider value in range, the offset gain formula must never let the
    ducked level reach or exceed the bed level, and must preserve the
    style's own duck depth exactly. This FAILS against the old one-sided
    fix (`bed_gain_db + offset, duck_gain_db` unchanged) the moment the
    offset passes roughly -4 to -6 dB depending on style - see the
    inversion thresholds in analysis.md RV6's table."""
    for style in _STYLES:
        gains = resolve_music_gains(style)
        original_depth = gains.bed_gain_db - gains.duck_gain_db
        for offset in _OFFSETS:
            bed, duck = offset_bed_and_duck_gain_db(gains.bed_gain_db, gains.duck_gain_db, offset)
            assert duck < bed, (
                f"{style} at offset {offset}: ducking inverted (bed={bed}, duck={duck})"
            )
            assert bed - duck == original_depth


def test_gain_offset_keeps_the_relative_duck_ratio_below_unity():
    """More direct expression of the same invariant, against the actual
    ffmpeg filter arithmetic `_volume_chain` builds: `relative_duck`
    (the multiplier applied on top of the base `volume=bed_linear` inside
    every narration window - see that function's own docstring) must stay
    below 1.0 for every offset, and must equal the un-offset style's own
    ratio exactly, since a uniform shift of both gains cancels out of the
    ratio entirely."""
    for style in _STYLES:
        gains = resolve_music_gains(style)
        original_ratio = _db_to_linear(gains.duck_gain_db) / _db_to_linear(gains.bed_gain_db)
        for offset in _OFFSETS:
            bed, duck = offset_bed_and_duck_gain_db(gains.bed_gain_db, gains.duck_gain_db, offset)
            relative_duck = _db_to_linear(duck) / _db_to_linear(bed)
            assert relative_duck < 1.0
            assert math.isclose(relative_duck, original_ratio, rel_tol=1e-9)


def test_gain_offset_filter_chain_still_gates_the_narration_window():
    """Sanity check that `_volume_chain` itself (not just the arithmetic
    feeding it) keeps building a valid, gated filter chain once fed the
    offset gains - one base `volume=` plus enable-gated `volume=` filters
    for the full duck and its ramp steps (OQ-1b)."""
    gains = resolve_music_gains("retention_fast")
    bed, duck = offset_bed_and_duck_gain_db(gains.bed_gain_db, gains.duck_gain_db, -20.0)
    chain = _volume_chain([(1.0, 2.5)], bed_gain_db=bed, duck_gain_db=duck)
    assert chain.startswith("volume=")
    # Do not split on "," — enable expressions contain escaped commas.
    assert "enable='between(t\\,1.000\\,2.500)'" in chain
    # Base + full duck + ramp steps (OQ-1b).
    assert chain.count("volume=") > 2


def test_duck_merge_threshold_matches_captions():
    assert DUCK_MERGE_THRESHOLD_S == MIN_CUE_DURATION_S == 0.8


def test_speaking_intervals_splits_on_long_hole_merges_on_short():
    """1.2 s hole → two ducks; 0.2 s hole → one merged duck."""
    alignment = {
        "characters": ["a", "b", "c", "d", "e"],
        "character_start_times_seconds": [0.0, 0.4, 1.8, 2.2, 2.5],
        # ends: 0–0.3, 0.4–0.6, then 1.8 (gap from 0.6 = 1.2 s) –2.0,
        # 2.2–2.35 (gap 0.2 s), 2.5–3.0
        "character_end_times_seconds": [0.3, 0.6, 2.0, 2.35, 3.0],
    }
    intervals = speaking_intervals_from_alignment([alignment])
    assert intervals == [(0.0, 0.6), (1.8, 3.0)]


def test_speaking_intervals_splits_on_long_newline_not_inter_char_gap():
    """§15.1: zero inter-character gaps; pause is a 0.40 s newline."""
    alignment = {
        "characters": ["h", "i", "\n", "b", "y"],
        "character_start_times_seconds": [0.00, 0.05, 0.10, 0.50, 0.55],
        "character_end_times_seconds": [0.05, 0.10, 0.50, 0.55, 0.60],
    }
    assert speaking_intervals_from_alignment([alignment]) == [(0.00, 0.10), (0.50, 0.60)]


def test_long_spoken_character_is_not_a_pause_when_letters_are_present():
    """A 0.5 s phoneme is speech; only whitespace that long releases the bed."""
    alignment = {
        "characters": ["a", "b"],
        "character_start_times_seconds": [0.0, 0.1],
        "character_end_times_seconds": [0.1, 0.6],
    }
    assert speaking_intervals_from_alignment([alignment]) == [(0.0, 0.6)]


def test_duration_only_split_when_characters_array_absent():
    """No `characters` key: any char longer than DUCK_CHAR_PAUSE_S is a pause."""
    alignment = {
        "character_start_times_seconds": [0.0, 0.1, 0.5],
        "character_end_times_seconds": [0.1, 0.5, 0.6],
    }
    # middle char is 0.4 s > 0.30
    assert speaking_intervals_from_alignment([alignment]) == [(0.0, 0.1), (0.5, 0.6)]


def test_speaking_intervals_concat_clock_across_scenes():
    """Scene 1 starts at scene 0's last character_end."""
    scene0 = {
        "characters": ["a", "b"],
        "character_start_times_seconds": [0.1, 0.5],
        "character_end_times_seconds": [0.4, 2.0],
    }
    scene1 = {
        "characters": ["c", "d"],
        "character_start_times_seconds": [0.0, 0.5],
        "character_end_times_seconds": [0.4, 1.0],
    }
    intervals = speaking_intervals_from_alignment([scene0, scene1])
    # scene0: leading 0.1 not ducked; chars merge (gap 0.1) → (0.1, 2.0)
    # scene1 at offset 2.0: (2.0, 3.0). Touching runs merge so ramps at
    # the scene join cannot double-multiply the relative duck.
    assert intervals == [(0.1, 3.0)]


def test_speaking_intervals_skips_malformed_scene():
    good = {
        "character_start_times_seconds": [0.0],
        "character_end_times_seconds": [1.0],
    }
    # RV-Q2: one unusable scene abandons the alignment path (empty list)
    # so mux_music falls back to file-duration intervals instead of
    # leaving later windows on a stuck concat clock.
    intervals = speaking_intervals_from_alignment([None, {"characters": []}, good])
    assert intervals == []


def test_none_then_scene_does_not_desync_clock():
    scene2 = {
        "character_start_times_seconds": [0.0],
        "character_end_times_seconds": [2.0],
    }
    assert speaking_intervals_from_alignment([None, scene2]) == []


def test_scene_boundary_gap_narrower_than_two_ramps_merges():
    """RV-Q3: 50 ms between scenes would overlap 80 ms ramps."""
    scene0 = {
        "characters": ["a"],
        "character_start_times_seconds": [0.0],
        "character_end_times_seconds": [2.0],
    }
    scene1 = {
        "characters": ["b"],
        "character_start_times_seconds": [0.05],
        "character_end_times_seconds": [2.0],
    }
    # scene1 starts at offset 2.0 → (2.05, 4.0); gap 50 ms < 2*0.08
    assert speaking_intervals_from_alignment([scene0, scene1]) == [(0.0, 4.0)]


def _overlapping_pairs(
    windows: list[tuple[float, float, float]],
) -> list[tuple[tuple[float, float, float], tuple[float, float, float]]]:
    """Window pairs that are simultaneously active. Chained `volume=`
    filters MULTIPLY where they overlap, so any pair here is a gain the
    envelope never intended."""
    return [
        (windows[i], windows[j])
        for i in range(len(windows))
        for j in range(i + 1, len(windows))
        if windows[i][0] < windows[j][1] - 1e-9 and windows[j][0] < windows[i][1] - 1e-9
    ]


def test_ramp_windows_never_overlap_on_back_to_back_intervals():
    """RV-Q3 reopened: the first fix guarded only the alignment path.

    `compute_narration_intervals` (the fallback RV-Q2's refusal routes
    into) returns per-scene intervals back to back with NO gap. Before
    the guard moved into `duck_ramp_windows`, a scene join had both full
    ducks and both ramp sets live at once — measured 16.1 dB below the
    intended floor for ~80 ms.
    """
    back_to_back = [(0.0, 2.0), (2.0, 4.0), (4.0, 6.0)]
    windows = duck_ramp_windows(back_to_back, relative_duck=0.5)

    assert _overlapping_pairs(windows) == []

    # And the envelope never dips below the duck floor anywhere.
    def gain_at(t: float) -> float:
        gain = 1.0
        for start, end, rel in windows:
            if start <= t <= end:
                gain *= rel
        return gain

    assert min(gain_at(1.8 + i * 0.001) for i in range(2500)) == pytest.approx(0.5)


def test_ramp_guard_is_idempotent_for_already_merged_intervals():
    """The guard must not change output the alignment path already got
    right — otherwise it would move `duck_envelope_hash` and re-render
    every cached mix for nothing."""
    well_spaced = [(0.0, 2.0), (2.2, 4.0)]
    assert duck_ramp_windows(well_spaced, relative_duck=0.5) == duck_ramp_windows(
        _merge_touching_intervals(well_spaced, min_gap_s=2 * DUCK_RAMP_S),
        relative_duck=0.5,
    )


def test_speaking_intervals_does_not_duck_leading_silence():
    alignment = {
        "characters": ["a"],
        "character_start_times_seconds": [0.5],
        "character_end_times_seconds": [1.5],
    }
    assert speaking_intervals_from_alignment([alignment]) == [(0.5, 1.5)]


def test_duck_ramp_windows_adds_stepped_sides():
    windows = duck_ramp_windows(
        [(1.0, 2.0)],
        relative_duck=0.5,
        ramp_s=DUCK_RAMP_S,
        steps=DUCK_RAMP_STEPS,
    )
    assert math.isclose(windows[0][0], 1.0 - DUCK_RAMP_S)
    assert math.isclose(windows[-1][1], 2.0 + DUCK_RAMP_S - DUCK_RAMP_S / DUCK_RAMP_STEPS)
    # 4 ramp-in + 1 full + 3 ramp-out (final gain=1.0 skipped) = 8
    assert len(windows) == DUCK_RAMP_STEPS + 1 + (DUCK_RAMP_STEPS - 1)
    full = [w for w in windows if w[0] == 1.0 and w[1] == 2.0]
    assert len(full) == 1
    assert full[0][2] == 0.5


def test_duck_ramp_first_and_last_step_times():
    ramp_s = 0.080
    steps = 4
    windows = duck_ramp_windows([(1.0, 2.0)], relative_duck=0.25, ramp_s=ramp_s, steps=steps)
    dt = ramp_s / steps
    assert math.isclose(windows[0][0], 1.0 - ramp_s)
    assert math.isclose(windows[0][1], 1.0 - ramp_s + dt)
    # Last emitted ramp-out step ends at end + (steps-1)*dt
    assert math.isclose(windows[-1][0], 2.0 + (steps - 2) * dt)
    assert math.isclose(windows[-1][1], 2.0 + (steps - 1) * dt)


def test_duck_envelope_hash_changes_when_intervals_change():
    a = duck_envelope_content_hash([(0.0, 1.0)])
    b = duck_envelope_content_hash([(0.0, 1.5)])
    assert a != b
    assert duck_envelope_content_hash([(0.0, 1.0)]) == a


def test_duck_envelope_hash_includes_merge_and_ramp_constants():
    base = duck_envelope_content_hash([(0.0, 1.0)])
    assert duck_envelope_content_hash([(0.0, 1.0)], merge_threshold_s=0.5) != base
    assert duck_envelope_content_hash([(0.0, 1.0)], ramp_s=0.05) != base
    assert duck_envelope_content_hash([(0.0, 1.0)], char_pause_s=0.5) != base


def test_touching_runs_across_scenes_merge():
    a = {
        "characters": ["a"],
        "character_start_times_seconds": [0.0],
        "character_end_times_seconds": [1.0],
    }
    b = {
        "characters": ["b"],
        "character_start_times_seconds": [0.0],
        "character_end_times_seconds": [1.0],
    }
    assert speaking_intervals_from_alignment([a, b]) == [(0.0, 2.0)]


# -- A11 (long_form_direction.md, 2026-09-01): diegetic-cue duck windows ----

_BED = -14.0
_NARR_DUCK = -20.0
_EFFECT_DUCK = -25.0
_NARR_REL = _db_to_linear(_NARR_DUCK) / _db_to_linear(_BED)
_EFFECT_REL = _db_to_linear(_EFFECT_DUCK) / _db_to_linear(_BED)


def test_no_effect_intervals_reproduces_the_narration_only_envelope():
    """The overwhelming majority case (no diegetic cues): `combine_duck_
    windows` + `duck_ramp_windows_segments` must be numerically IDENTICAL
    to the pre-A11 `duck_ramp_windows` path - this is what makes A11 safe
    to ship without moving a single existing project's audio."""
    narration = [(1.0, 2.0), (3.0, 4.0)]
    combined = combine_duck_windows(narration, _NARR_DUCK, [], _NARR_DUCK, bed_gain_db=_BED)
    assert combined == [(1.0, 2.0, _NARR_REL), (3.0, 4.0, _NARR_REL)]
    assert duck_ramp_windows_segments(combined) == duck_ramp_windows(
        narration, relative_duck=_NARR_REL
    )


def test_effect_window_with_no_narration_overlap_plays_at_its_own_depth():
    combined = combine_duck_windows([], _NARR_DUCK, [(10.0, 12.0)], _EFFECT_DUCK, bed_gain_db=_BED)
    assert combined == [(10.0, 12.0, _EFFECT_REL)]


def _gain_at(t: float, windows: list[tuple[float, float, float]]) -> float:
    gain = 1.0
    for start, end, rel in windows:
        if start <= t <= end:
            gain *= rel
    return gain


def test_overlapping_cue_takes_the_deeper_depth_not_the_product():
    """A11's core requirement: a cue mid-narration must not double-duck
    into mud. Effect is deeper here (-25 vs -20 dB) - the overlap must
    read at the effect's OWN depth, never `_NARR_REL * _EFFECT_REL`."""
    combined = combine_duck_windows(
        [(0.0, 5.0)], _NARR_DUCK, [(2.0, 3.0)], _EFFECT_DUCK, bed_gain_db=_BED
    )
    ramped = duck_ramp_windows_segments(combined)
    assert _gain_at(2.5, ramped) == pytest.approx(_EFFECT_REL)
    assert _gain_at(2.5, ramped) != pytest.approx(_NARR_REL * _EFFECT_REL)


def test_nested_effect_window_does_not_flatten_the_surrounding_narration():
    """Regression for a real bug found while building this: an earlier
    version merged ANY touching segments regardless of depth, which
    collapsed an entire 60s narration span to the effect's depth the
    moment a 3s cue touched it anywhere inside. The narration on EITHER
    SIDE of the cue must keep its own (shallower) depth."""
    combined = combine_duck_windows(
        [(0.0, 60.0)], _NARR_DUCK, [(30.0, 33.0)], _EFFECT_DUCK, bed_gain_db=_BED
    )
    ramped = duck_ramp_windows_segments(combined)
    assert _gain_at(15.0, ramped) == pytest.approx(_NARR_REL)
    assert _gain_at(31.5, ramped) == pytest.approx(_EFFECT_REL)
    assert _gain_at(45.0, ramped) == pytest.approx(_NARR_REL)
    assert _gain_at(-1.0, ramped) == pytest.approx(1.0)
    assert _gain_at(61.0, ramped) == pytest.approx(1.0)


def test_junction_between_two_depths_never_ramps_back_through_the_bed():
    """The failure mode a naive "independent ramp in/out" implementation
    hits: at a touching boundary between two DIFFERENT depths, ramping
    segment A out to 1.0 and segment B in from 1.0 would briefly pop back
    toward full bed volume between two ducks that are effectively
    continuous. Sampling densely across the junction must never approach
    1.0 (it should move directly between the two duck depths)."""
    combined = combine_duck_windows(
        [(0.0, 30.0)], _NARR_DUCK, [(30.0, 33.0)], _EFFECT_DUCK, bed_gain_db=_BED
    )
    ramped = duck_ramp_windows_segments(combined)
    samples = [_gain_at(30.0 + i * 0.002, ramped) for i in range(-20, 21)]
    bed_level = 1.0
    # Every sample near the junction must sit at or below the SHALLOWER
    # of the two depths (never drift back up toward the unducked bed).
    assert max(samples) <= max(_NARR_REL, _EFFECT_REL) + 1e-9
    assert all(sample < bed_level - 1e-6 for sample in samples)


def test_far_apart_different_depths_ramp_independently_through_the_bed():
    """A genuine silence gap (> 2*DUCK_RAMP_S) between a narration window
    and a cue window elsewhere is NOT a junction - the bed must actually
    come back up in between, same as two ordinary narration windows."""
    combined = combine_duck_windows(
        [(0.0, 1.0)], _NARR_DUCK, [(6.0, 8.0)], _EFFECT_DUCK, bed_gain_db=_BED
    )
    ramped = duck_ramp_windows_segments(combined)
    assert _gain_at(3.0, ramped) == pytest.approx(1.0)
    assert _overlapping_pairs(ramped) == []


def test_combined_ramp_windows_never_overlap():
    """RV-Q3's own invariant, extended to the two-depth case: chained
    `volume=` filters multiply where they overlap, so the combined,
    ramped envelope must never contain two simultaneously-active windows
    (beyond the single-instant touch point ffmpeg's own inclusive
    `between()` already accepts at ordinary same-depth boundaries)."""
    combined = combine_duck_windows(
        [(0.0, 10.0), (20.0, 21.0)],
        _NARR_DUCK,
        [(5.0, 6.0), (25.0, 26.0)],
        _EFFECT_DUCK,
        bed_gain_db=_BED,
    )
    ramped = duck_ramp_windows_segments(combined)
    assert _overlapping_pairs(ramped) == []


def test_newline_pauses_do_not_overlap_ramps():
    """§15.1: real splits finally create inter-interval gaps; ramps must not multiply."""
    alignment = {
        "characters": ["a", "\n", "b"],
        "character_start_times_seconds": [0.0, 0.2, 0.6],
        "character_end_times_seconds": [0.2, 0.6, 0.8],
    }
    intervals = speaking_intervals_from_alignment([alignment])
    assert intervals == [(0.0, 0.2), (0.6, 0.8)]
    windows = duck_ramp_windows(intervals, relative_duck=0.5)
    assert _overlapping_pairs(windows) == []
    assert DUCK_CHAR_PAUSE_S == 0.30
