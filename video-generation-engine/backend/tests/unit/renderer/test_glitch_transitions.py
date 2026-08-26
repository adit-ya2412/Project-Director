"""Feature C - glitch transitions (style_extensions.md §5, P-C2/P-C3):
`app/renderer/slideshow.py`'s `_glitch_transition_filter` and its wiring
into the two xfade call sites.

Pure filter-string composition and mocked-ffmpeg wiring tests only - no
DB, no ffmpeg needed for most cases (mirrors test_slideshow_argv.py's own
stated split: argv/graph shape here, real bytes in the integration
suite). The one real-ffmpeg case at the bottom mirrors
test_caption_highlight.py's burn-in test - real ffmpeg, zero DB contact.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

from app.renderer.slideshow import (
    _GLITCH_TRANSITIONS,
    RenderSettings,
    _glitch_transition_filter,
    _xfade_shot_streams,
)
from app.schemas.timeline import (
    Camera,
    CameraMovement,
    Shot,
    ShotIntent,
    Transition,
    TransitionType,
)

_GLITCH_TYPES = (
    TransitionType.GLITCH_SHIFT,
    TransitionType.GLITCH_TEAR,
    TransitionType.GLITCH_JITTER,
)


def _settings(width: int = 720, height: int = 1280) -> RenderSettings:
    return RenderSettings(width=width, height=height, fps=25, pixel_format="yuv420p")


# ---------------------------------------------------------------------------
# `_glitch_transition_filter` - pure filter-string composition
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("transition", _GLITCH_TYPES)
def test_every_glitch_type_is_in_the_membership_set(transition):
    assert transition in _GLITCH_TRANSITIONS


@pytest.mark.parametrize("transition", _GLITCH_TYPES)
def test_glitch_fragment_starts_with_a_plain_fade_and_ends_at_out_label(transition):
    frag = _glitch_transition_filter(
        "a0",
        "a1",
        transition,
        duration_s=0.5,
        offset_s=1.5,
        out_label="vout",
        settings=_settings(),
    )
    assert frag.startswith("[a0][a1]xfade=transition=fade:duration=0.500:offset=1.500[")
    assert frag.rstrip().endswith("[vout]")
    # The enable window is exactly [offset, offset+duration] (D5's own
    # arithmetic must reach here unmodified, never the spike's hardcoded
    # 1.5/0.5) - both stated in seconds to 3 decimal places.
    assert "between(t,1.500,2.000)" in frag


@pytest.mark.parametrize("transition", _GLITCH_TYPES)
def test_glitch_fragment_carries_real_duration_and_offset_not_hardcoded(transition):
    """D5's real per-cut arithmetic, not the spike's fixed 1.5/0.5."""
    frag = _glitch_transition_filter(
        "p",
        "c",
        transition,
        duration_s=0.833,
        offset_s=12.417,
        out_label="x3",
        settings=_settings(),
    )
    assert "duration=0.833:offset=12.417" in frag
    assert "between(t,12.417,13.250)" in frag
    assert "1.500" not in frag and "0.500" not in frag


def test_glitch_shift_is_rgbashift_plus_noise_only():
    frag = _glitch_transition_filter(
        "a",
        "b",
        TransitionType.GLITCH_SHIFT,
        duration_s=0.5,
        offset_s=1.5,
        out_label="vout",
        settings=_settings(),
    )
    assert "rgbashift=" in frag
    assert "noise=" in frag
    assert "crop=" not in frag  # no jitter/tear stage
    assert "overlay=" not in frag  # no tear stage


def test_glitch_jitter_adds_a_crop_wobble_stage_before_the_shift():
    frag = _glitch_transition_filter(
        "a",
        "b",
        TransitionType.GLITCH_JITTER,
        duration_s=0.5,
        offset_s=1.5,
        out_label="vout",
        settings=_settings(),
    )
    assert "crop=720:1280:" in frag
    assert "overlay=" not in frag  # jitter is crop-based, not overlay-based (that's tear)
    # The crop stage must feed the rgbashift stage, not the other way
    # round - stage order matters for how the two effects compose.
    assert frag.index("crop=") < frag.index("rgbashift=")


def test_glitch_tear_adds_two_band_displacement_stages():
    frag = _glitch_transition_filter(
        "a",
        "b",
        TransitionType.GLITCH_TEAR,
        duration_s=0.5,
        offset_s=1.5,
        out_label="vout",
        settings=_settings(),
    )
    assert frag.count("overlay=") == 2
    assert frag.count("split") == 2
    assert "crop=" in frag


def test_glitch_labels_never_collide_across_two_transitions_in_one_graph():
    """Two glitch transitions in the same run must not share a single
    intermediate label - `out_label` namespaces every internal label."""
    frag1 = _glitch_transition_filter(
        "n0",
        "n1",
        TransitionType.GLITCH_TEAR,
        duration_s=0.5,
        offset_s=1.5,
        out_label="x1",
        settings=_settings(),
    )
    frag2 = _glitch_transition_filter(
        "x1",
        "n2",
        TransitionType.GLITCH_TEAR,
        duration_s=0.5,
        offset_s=3.0,
        out_label="x2",
        settings=_settings(),
    )
    labels1 = {tok.split("]")[0] for tok in frag1.split("[") if "]" in tok}
    labels2 = {tok.split("]")[0] for tok in frag2.split("[") if "]" in tok}
    # Every internal (non-shared-boundary) label must be disjoint.
    boundary = {"n0", "n1", "x1", "n2", "x2"}
    assert (labels1 - boundary).isdisjoint(labels2 - boundary)


def test_glitch_scale_shift_magnitudes_by_width_ratio_not_height():
    """Regression: `rv`/`bv`/`gv` are shift MAGNITUDES, not frame
    positions - they must scale with the same width ratio as `rh`/`bh`,
    not the height ratio (which is far more extreme for a portrait frame
    against the landscape-ish 480x270 reference and was never what
    style_extensions.md's real-resolution check actually validated)."""
    # 720x1280: width ratio 1.5x, height ratio ~4.74x - deliberately
    # different so the two are distinguishable in the assertion below.
    frag = _glitch_transition_filter(
        "a",
        "b",
        TransitionType.GLITCH_JITTER,
        duration_s=0.5,
        offset_s=1.5,
        out_label="vout",
        settings=_settings(720, 1280),
    )
    # rv=5*1.5=8 (width ratio) - NOT 5*4.74≈24 (height ratio).
    assert "rv=-8:bv=8" in frag
    assert "rv=-24" not in frag


def test_glitch_tear_band_positions_scale_by_height_the_other_bands_by_width():
    """Unlike shift magnitudes, `GLITCH_TEAR`'s band y-position/height ARE
    frame positions - those scale with height ratio; the bands' own
    x-displacement amount is a shift magnitude and scales with width."""
    frag = _glitch_transition_filter(
        "a",
        "b",
        TransitionType.GLITCH_TEAR,
        duration_s=0.5,
        offset_s=1.5,
        out_label="vout",
        settings=_settings(720, 1280),
    )
    hr = 1280 / 270
    wr = 720 / 480
    assert f"crop=iw:{round(34*hr)}:0:{round(60*hr)}" in frag
    assert f"*{round(90*wr)}" in frag


def test_glitch_fragment_is_a_single_semicolon_joined_string_ready_for_the_script_file():
    """The caller (`_xfade_shot_streams`/`_render_run`) appends this
    directly into a `;`-joined filters list, same as every plain xfade
    line - it must not itself end in a trailing `;` or contain a raw
    newline."""
    frag = _glitch_transition_filter(
        "a",
        "b",
        TransitionType.GLITCH_TEAR,
        duration_s=0.5,
        offset_s=1.5,
        out_label="vout",
        settings=_settings(),
    )
    assert "\n" not in frag
    assert not frag.endswith(";")


# ---------------------------------------------------------------------------
# Wiring: a glitch transition reaches the real filter script, both call sites
# ---------------------------------------------------------------------------


def _shot(shot_id: str, transition: TransitionType, duration_s: float = 1.5) -> Shot:
    return Shot(
        id=shot_id,
        order=0,
        intent=ShotIntent.EXPLAIN,
        duration_s=duration_s,
        camera=Camera(movement=CameraMovement.STATIC),
        transition_out=Transition(type=transition, duration_s=0.5),
    )


async def test_xfade_shot_streams_wires_a_glitch_transition_into_the_written_filter_script(
    tmp_path, monkeypatch
):
    """§P-C3: `_xfade_shot_streams` is the real call site
    `_render_run_two_pass` uses for every multi-shot run (`_render_run`'s
    OWN inline transition loop is dead code for >=2 shots - it always
    delegates to two-pass, per its own docstring: "Multi-shot runs use
    two-pass (C3 (d))"). A shot with `transition_out.type=GLITCH_SHIFT`
    must produce the custom fragment in the actual `.xfade.filter` file
    written to disk - never the plain `xfade=transition=glitch_shift`
    line every real transition name gets (which `xfade` has no such
    transition for and would fail on)."""
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    src1 = work_dir / "stream0.mp4"
    src2 = work_dir / "stream1.mp4"
    src1.write_bytes(b"not-a-real-mp4")
    src2.write_bytes(b"not-a-real-mp4")
    output_path = work_dir / "run_000.mp4"

    async def fake_ffmpeg(args, *, cwd=None):
        (cwd / args[-1] if cwd is not None else Path(args[-1])).write_bytes(b"mp4")

    monkeypatch.setattr("app.renderer.slideshow.run_ffmpeg", fake_ffmpeg)

    shots = [_shot("sh_01", TransitionType.GLITCH_SHIFT), _shot("sh_02", TransitionType.CUT)]
    await _xfade_shot_streams(shots, [src1, src2], _settings(), output_path, work_dir=work_dir)

    script = work_dir / "run_000.xfade.filter"
    graph = script.read_text(encoding="utf-8")
    assert "rgbashift=" in graph
    assert "noise=" in graph
    assert "xfade=transition=glitch_shift" not in graph  # never a bare xfade name
    assert "xfade=transition=fade:" in graph  # the glitch fragment's own inner fade


# ---------------------------------------------------------------------------
# Real burn: the generated fragment must survive an actual ffmpeg encode
# ---------------------------------------------------------------------------


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
@pytest.mark.parametrize("transition", _GLITCH_TYPES)
def test_glitch_fragment_runs_through_a_real_ffmpeg_encode(transition, tmp_path):
    frag = _glitch_transition_filter(
        "0:v",
        "1:v",
        transition,
        duration_s=0.3,
        offset_s=0.5,
        out_label="vout",
        settings=_settings(160, 90),
    )
    out_path = tmp_path / "out.mp4"
    result = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=red:s=160x90:d=1:r=10",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=160x90:d=1:r=10",
            "-filter_complex",
            frag,
            "-map",
            "[vout]",
            "-frames:v",
            "15",
            "-y",
            out_path.as_posix(),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert out_path.stat().st_size > 0
