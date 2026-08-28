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
    DUCK_MERGE_THRESHOLD_S,
    DUCK_RAMP_S,
    DUCK_RAMP_STEPS,
    _db_to_linear,
    _merge_touching_intervals,
    _volume_chain,
    duck_envelope_content_hash,
    duck_ramp_windows,
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
        "character_start_times_seconds": [0.0, 0.4, 1.8, 2.2, 2.5],
        # ends: 0–0.3, 0.4–0.6, then 1.8 (gap from 0.6 = 1.2 s) –2.0,
        # 2.2–2.35 (gap 0.2 s), 2.5–3.0
        "character_end_times_seconds": [0.3, 0.6, 2.0, 2.35, 3.0],
    }
    intervals = speaking_intervals_from_alignment([alignment])
    assert intervals == [(0.0, 0.6), (1.8, 3.0)]


def test_speaking_intervals_concat_clock_across_scenes():
    """Scene 1 starts at scene 0's last character_end."""
    scene0 = {
        "character_start_times_seconds": [0.1, 0.5],
        "character_end_times_seconds": [0.4, 2.0],
    }
    scene1 = {
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
        "character_start_times_seconds": [0.0],
        "character_end_times_seconds": [2.0],
    }
    scene1 = {
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


def test_touching_runs_across_scenes_merge():
    a = {
        "character_start_times_seconds": [0.0],
        "character_end_times_seconds": [1.0],
    }
    b = {
        "character_start_times_seconds": [0.0],
        "character_end_times_seconds": [1.0],
    }
    assert speaking_intervals_from_alignment([a, b]) == [(0.0, 2.0)]
