"""`app/renderer/music.py` - pure gain arithmetic, no ffmpeg needed.

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
"""

import math

from app.renderer.music import _db_to_linear, _volume_chain, offset_bed_and_duck_gain_db
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
                f"{style} at offset {offset}: ducking inverted " f"(bed={bed}, duck={duck})"
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
    offset gains - one base `volume=` plus one `enable`-gated `volume=`
    per interval, exactly as its own docstring describes."""
    gains = resolve_music_gains("retention_fast")
    bed, duck = offset_bed_and_duck_gain_db(gains.bed_gain_db, gains.duck_gain_db, -20.0)
    chain = _volume_chain([(1.0, 2.5)], bed_gain_db=bed, duck_gain_db=duck)
    base, gated = chain.split(",", 1)
    assert base.startswith("volume=")
    assert gated.startswith("volume=")
    assert "enable='between(t\\,1.000\\,2.500)'" in gated
