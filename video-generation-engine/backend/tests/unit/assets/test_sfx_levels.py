"""C3c/C3d (analysis.md, decision 5b): pure level math + the real-ffmpeg
volumedetect probe. No DB - safe under `--noconftest`."""

import shutil
import subprocess

import pytest

from app.assets.sfx_levels import (
    effective_gain_db,
    end_aligned_trim_start,
    gain_to_target_db,
    measure_peak_dbfs,
)
from app.core.config import settings

_FFMPEG = shutil.which(settings.ffmpeg_binary) or shutil.which("ffmpeg")


# -- gain math ---------------------------------------------------------------


def test_gain_to_target_is_the_difference():
    assert gain_to_target_db(-1.9, -8.0) == pytest.approx(-6.1)
    assert gain_to_target_db(-12.0, -8.0) == pytest.approx(4.0)


def test_effective_gain_normalizes_a_measured_peak_onto_the_target():
    assert effective_gain_db(-1.9, target_db=-8.0, fallback_db=-99.0) == pytest.approx(-6.1)


def test_unmeasured_clip_falls_back_to_the_flat_gain():
    assert effective_gain_db(None, target_db=-8.0, fallback_db=-8.0) == -8.0


def test_kind_offset_rides_on_top_of_both_paths():
    base = effective_gain_db(-3.0, target_db=-8.0, fallback_db=-50.0, kind_offset_db=-2.0)
    assert base == pytest.approx(-7.0)  # (-8 - -3) + -2
    fallback = effective_gain_db(None, target_db=-8.0, fallback_db=-8.0, kind_offset_db=1.5)
    assert fallback == pytest.approx(-6.5)


def test_normalize_target_is_a_peak_target_not_the_flat_gain_fallback():
    """RV11 / analysis.md C3c: `sfx_normalize_target_db` (an absolute
    output PEAK target) and `sfx_gain_db` (a flat GAIN fallback, -8.0)
    are two different quantities that must never collapse to the same
    number again - see the config.py comment this pins.

    The target was lowered -12.0 -> -20.0 on 2026-08-27 against measured
    narration levels; this test pins the INVARIANT (they stay distinct,
    and the target stays below the gain fallback), not the tuning value,
    so a future level pass does not have to edit it.
    """
    assert settings.sfx_gain_db == pytest.approx(-8.0)
    assert settings.sfx_normalize_target_db != settings.sfx_gain_db
    # The P6 failure was the target landing ABOVE (louder than) the
    # fallback. Any sane target sits below it.
    assert settings.sfx_normalize_target_db < settings.sfx_gain_db


def test_sfx_peaks_land_under_the_measured_narration_average():
    """2026-08-27: the reason the target moved. Real narration on
    d3a4d00d measured mean -22.3 dBFS / peak -2.8 dBFS. Speech has a
    high crest factor, so an SFX peak target chosen in isolation says
    nothing about how the effect sits against the voice - the old -12.0
    put every transient ~10 dB OVER the average narration level.

    Pinned as a relationship, not a number: whatever the target is, a
    normalized clip must not peak far above where narration actually
    sits."""
    narration_mean_dbfs = -22.3
    for source_peak in (-5.0, -7.3, -9.3):  # the real library's 3 clips
        gain = effective_gain_db(
            source_peak,
            target_db=settings.sfx_normalize_target_db,
            fallback_db=settings.sfx_gain_db,
        )
        played_peak = source_peak + gain
        assert played_peak == pytest.approx(settings.sfx_normalize_target_db)
        assert played_peak < narration_mean_dbfs + 3.0


def test_known_peak_normalizes_onto_the_target_and_gets_quieter():
    """A clip peaking at -5.0 dBFS (analysis.md RV11's stinger example)
    must be attenuated onto the target, never amplified - the specific
    regression P6 introduced."""
    gain = effective_gain_db(
        -5.0,
        target_db=settings.sfx_normalize_target_db,
        fallback_db=settings.sfx_gain_db,
    )
    assert gain < 0.0
    assert -5.0 + gain == pytest.approx(settings.sfx_normalize_target_db)


# -- end-aligned trim start --------------------------------------------------


def test_fitting_clip_trims_from_the_head():
    assert end_aligned_trim_start(0.49, 1.5) == 0.0


def test_overlong_clip_keeps_its_tail():
    """C3d's whole point: a 3.156s clip under a 1.5s ceiling starts at
    1.656s so the impact transient at the END survives."""
    assert end_aligned_trim_start(3.156, 1.5) == pytest.approx(1.656)


def test_unknown_duration_never_invents_an_offset():
    assert end_aligned_trim_start(None, 1.5) == 0.0


def test_degenerate_inputs_are_safe():
    assert end_aligned_trim_start(3.0, 0.0) == 0.0
    assert end_aligned_trim_start(0.0, 1.5) == 0.0


# -- the volumedetect probe (real ffmpeg) ------------------------------------


@pytest.mark.skipif(_FFMPEG is None, reason="ffmpeg not installed")
async def test_full_scale_sine_measures_near_zero_dbfs(tmp_path):
    out = tmp_path / "loud.wav"
    subprocess.run(
        [
            settings.ffmpeg_binary,
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=0.5",
            str(out),
        ],
        check=True,
        capture_output=True,
    )
    peak = await measure_peak_dbfs(out)
    assert peak is not None
    # ffmpeg's `sine` source generates at exactly 1/8 amplitude =
    # -18.1 dBFS - asserting the KNOWN value proves the regex parsed
    # volumedetect's output correctly, not just that it returned something.
    assert peak == pytest.approx(-18.1, abs=0.5)


@pytest.mark.skipif(_FFMPEG is None, reason="ffmpeg not installed")
def test_garbage_bytes_measure_none(tmp_path):
    junk = tmp_path / "junk.mp3"
    junk.write_bytes(b"<html>not audio</html>")

    import asyncio

    assert asyncio.run(measure_peak_dbfs(junk)) is None
