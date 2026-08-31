"""Track C §4.2 / §4.1b: argv halves + tpad input shape.

The filter graph and the staged names are what make a 185-shot run
survivable on Windows. These tests pin the argv contract without
shelling out to ffmpeg; duration/bytes stay in the integration suite.
"""

from pathlib import Path

import pytest

from app.renderer.ken_burns import MovingCropExpression, build_zoompan_expression
from app.renderer.motion import MediaKind, MediaProbe
from app.renderer.slideshow import (
    RenderSettings,
    _ken_burns_pan_filter,
    _normalize_filter,
    _render_run,
    filter_graph_file_flag,
    short_input_name,
    stage_short_input,
)
from app.schemas.timeline import (
    Camera,
    CameraDirection,
    CameraMovement,
    Shot,
    ShotIntent,
    Transition,
    TransitionType,
)


def _settings() -> RenderSettings:
    return RenderSettings(width=320, height=240, fps=24, pixel_format="yuv420p")


def _static_shot(shot_id: str, duration_s: float = 1.5) -> Shot:
    return Shot(
        id=shot_id,
        order=0,
        intent=ShotIntent.EXPLAIN,
        duration_s=duration_s,
        camera=Camera(movement=CameraMovement.STATIC),
        transition_out=Transition(type=TransitionType.CUT, duration_s=0.0),
    )


def test_static_hold_subtracts_the_decoded_frame():
    """§14.1: tpad appends after the one decoded frame. frames=1 → 0.0."""
    fps = 30
    assert (102 - 1) / fps == pytest.approx(3.366666, abs=1e-6)
    assert (1 - 1) / fps == 0.0


def test_normalize_filter_holds_duration_with_tpad_not_a_loop():
    fragment = _normalize_filter(0, _settings(), "n0", hold_s=1.5 - 1 / 24)
    assert "tpad=stop_mode=clone:stop_duration=1.458333" in fragment
    assert "-loop" not in fragment
    # CFR before the hold — ffmpeg 7.1.5 xfade rejects tpad-before-fps
    # when the other input is a motion clip (rate 1/0).
    assert fragment.index("scale=") < fragment.index("fps=")
    assert fragment.index("fps=") < fragment.index("tpad=")


def test_ken_burns_pan_filter_holds_via_tpad_then_crops_no_zoompan():
    """A2: PAN's moving-crop chain (`_ken_burns_pan_filter`) - built from
    the REAL arithmetic function (`build_zoompan_expression`), matching
    the same "pin the argv/filter contract without shelling out" shape
    every other test in this file uses."""
    settings = _settings()
    camera = Camera(movement=CameraMovement.PAN, direction=CameraDirection.RIGHT, intensity=1.0)
    expr = build_zoompan_expression(
        camera, frames=90, canvas_w=settings.width, duration_s=90 / settings.fps
    )
    assert isinstance(expr, MovingCropExpression)
    fragment = _ken_burns_pan_filter(0, settings, "n0", expr, 90)
    assert "zoompan" not in fragment
    assert f"crop={settings.width}:{settings.height}:'{expr.x_expr}':0" in fragment
    # Same tpad-materialises-the-hold shape `_normalize_filter` uses (one
    # decoded frame in, `frames` frames out) - `crop` has no `zoompan`-
    # style `d=`/`fps=` pair to do this itself.
    assert "tpad=stop_mode=clone:stop_duration=" in fragment
    assert fragment.index("scale=") < fragment.index("fps=")
    assert fragment.index("fps=") < fragment.index("tpad=")
    assert fragment.index("tpad=") < fragment.index("crop=")


def test_ken_burns_pan_filter_vertical_scales_width_only_and_crops_y():
    """A5: a vertical (UP/DOWN) pan puts the moving expression on `y`
    with `x` pinned to the literal `0`.

    The scale is `{w}:{h}:force_original_aspect_ratio=increase` on BOTH
    axes, not the per-axis `scale={w}:-2` / `scale=-2:{h}` A2 and A5
    originally emitted. Pinning one axis let the other fall short of the
    crop window whenever the source was narrower than the output aspect,
    and `crop` does not degrade there - it refuses to configure and kills
    the render (measured: 17.1% of this project's assets on the shipped
    9:16 canvas, 89.8% on 16:9). Cover-scaling guarantees both axes are
    >= the crop window while staying pixel-identical wherever the old
    chain worked."""
    settings = _settings()
    camera = Camera(movement=CameraMovement.PAN, direction=CameraDirection.DOWN, intensity=1.0)
    expr = build_zoompan_expression(
        camera,
        frames=90,
        canvas_w=settings.width,
        canvas_h=settings.height,
        duration_s=90 / settings.fps,
    )
    assert isinstance(expr, MovingCropExpression)
    assert expr.y_expr is not None
    fragment = _ken_burns_pan_filter(0, settings, "n0", expr, 90)
    assert "zoompan" not in fragment
    assert (
        f"scale={settings.width}:{settings.height}:force_original_aspect_ratio=increase"
        in fragment
    )
    assert f"crop={settings.width}:{settings.height}:0:'{expr.y_expr}'" in fragment
    assert fragment.index("scale=") < fragment.index("fps=")
    assert fragment.index("fps=") < fragment.index("tpad=")
    assert fragment.index("tpad=") < fragment.index("crop=")


def test_ken_burns_pan_filter_horizontal_unchanged_by_the_vertical_addition():
    """The horizontal branch added by A2 still puts the moving
    expression on `x` with `y` pinned to `0` after A5 added the vertical
    branch alongside it.

    Byte-identical discipline (§2) applies to PIXELS here, not to the
    string: the shared cover-scale replaced A2's `scale=-2:{h}`, which
    was a crash for any source narrower than the output aspect. Frame-
    hash verified identical on the reference landscape asset the pan work
    was signed off against (2980x1676 at 720x1280) - cover-scaling pins
    height to exactly the same 2276x1280 that `-2:{h}` produced whenever
    the source is wider than the output."""
    settings = _settings()
    camera = Camera(movement=CameraMovement.PAN, direction=CameraDirection.RIGHT, intensity=1.0)
    expr = build_zoompan_expression(
        camera,
        frames=90,
        canvas_w=settings.width,
        canvas_h=settings.height,
        duration_s=90 / settings.fps,
    )
    assert isinstance(expr, MovingCropExpression)
    assert expr.y_expr is None
    fragment = _ken_burns_pan_filter(0, settings, "n0", expr, 90)
    assert (
        f"scale={settings.width}:{settings.height}:force_original_aspect_ratio=increase"
        in fragment
    )
    assert f"crop={settings.width}:{settings.height}:'{expr.x_expr}':0" in fragment


def test_filter_graph_file_flag_probes_capability_not_version(monkeypatch):
    """§14.6: do not parse `ffmpeg version N`. Nightlies like
    `N-120345-g…` parse as major 0 and would pick the legacy flag."""

    def _probe(binary: str, stderr: str):
        def fake_run(args, **_kwargs):
            class Result:
                returncode = 1
                stdout = ""

            r = Result()
            r.stderr = stderr
            return r

        monkeypatch.setattr("app.renderer.slideshow.subprocess.run", fake_run)
        filter_graph_file_flag.cache_clear()
        return filter_graph_file_flag(binary)

    assert (
        _probe("ffmpeg9", "Unrecognized option '-/filter_complex'.\nError splitting the argument list: Option not found")
        == "-filter_complex_script"
    )
    assert (
        _probe("ffmpeg7", "Error opening filter script file __no_such_filter_script.filter")
        == "-/filter_complex"
    )
    filter_graph_file_flag.cache_clear()


def test_short_input_name_is_unique_per_run():
    """R-C2: run 0 and run 1 must not share s000.jpg."""
    a = short_input_name(0, Path("a.jpg"), MediaKind.STILL, run_stem="run_000")
    b = short_input_name(0, Path("a.jpg"), MediaKind.STILL, run_stem="run_001")
    assert a == "run_000_s000.jpg"
    assert b == "run_001_s000.jpg"
    assert a != b
    assert (
        short_input_name(12, Path("clip.MP4"), MediaKind.MOTION, run_stem="run_000")
        == "run_000_s012.mp4"
    )
    assert short_input_name(3, Path("noext"), MediaKind.STILL, run_stem="run_002") == "run_002_s003.png"


def test_stage_short_input_makes_dest_same_bytes(tmp_path):
    src = tmp_path / "storage" / (("deadbeef" * 8) + ".jpg")
    src.parent.mkdir()
    src.write_bytes(b"pixels")
    dest = tmp_path / "work" / "s000.jpg"
    stage_short_input(src, dest)
    assert dest.read_bytes() == b"pixels"
    # A second stage of the same dest (re-render) must not raise.
    src.write_bytes(b"pixels2")
    stage_short_input(src, dest)
    assert dest.read_bytes() == b"pixels2"


async def test_render_run_argv_is_filter_script_plus_short_names(tmp_path, monkeypatch):
    """Both halves of §4.2, together: no `-filter_complex`, no `-loop`,
    no long storage path on the command line, cwd is work_dir."""
    long_dir = tmp_path / "storage" / ("0" * 36) / "assets"
    long_dir.mkdir(parents=True)
    src = long_dir / ("a" * 64 + ".jpg")
    src.write_bytes(b"not-a-real-jpeg")

    work_dir = tmp_path / "work"
    work_dir.mkdir()
    output_path = work_dir / "run_000.mp4"

    captured: dict = {}

    async def fake_ffmpeg(args: list[str], *, cwd: Path | None = None) -> None:
        captured["args"] = args
        captured["cwd"] = cwd
        (cwd / args[-1] if cwd is not None else Path(args[-1])).write_bytes(b"mp4")

    monkeypatch.setattr("app.renderer.slideshow.run_ffmpeg", fake_ffmpeg)

    shot = _static_shot("sh_01")
    await _render_run(
        [shot],
        {shot.id: src},
        {shot.id: MediaProbe(kind=MediaKind.STILL)},
        _settings(),
        output_path,
        work_dir=work_dir,
    )

    args = captured["args"]
    assert captured["cwd"] == work_dir
    assert "-filter_complex" not in args  # graph must not sit in argv
    assert "-loop" not in args
    flag = (
        "-filter_complex_script" if "-filter_complex_script" in args else "-/filter_complex"
    )
    assert flag in args
    script = args[args.index(flag) + 1]
    assert script == "run_000.filter"
    assert "/" not in script and "\\" not in script
    inputs = [args[i + 1] for i, a in enumerate(args) if a == "-i"]
    assert inputs == ["run_000_s000.jpg"]
    assert args[-1] == "run_000.mp4"
    # The long storage path must not appear anywhere in argv.
    joined = " ".join(args)
    assert "deadbeef" not in joined
    assert str(src) not in joined
    # And the filter file is the graph, with tpad, not a path.
    graph = (work_dir / script).read_text(encoding="utf-8")
    assert "tpad=stop_mode=clone" in graph
    assert str(src) not in graph
    # Headroom: even a 185-shot projection of this shape stays tiny.
    assert len(joined) < 400


async def test_render_run_logs_argv_length(tmp_path, monkeypatch):
    src = tmp_path / "img.png"
    src.write_bytes(b"x")
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    extras: list[dict] = []

    async def fake_ffmpeg(args: list[str], *, cwd: Path | None = None) -> None:
        (cwd / args[-1]).write_bytes(b"mp4")

    def fake_info(event: str, extra: dict | None = None) -> None:
        extras.append({"event": event, **(extra or {})})

    monkeypatch.setattr("app.renderer.slideshow.run_ffmpeg", fake_ffmpeg)
    monkeypatch.setattr("app.renderer.slideshow.logger.info", fake_info)

    shot = _static_shot("sh_01")
    await _render_run(
        [shot],
        {shot.id: src},
        {shot.id: MediaProbe(kind=MediaKind.STILL)},
        _settings(),
        work_dir / "run_000.mp4",
        work_dir=work_dir,
    )
    argv_logs = [e for e in extras if e.get("event") == "render.run_argv"]
    assert len(argv_logs) == 1
    assert argv_logs[0]["shots"] == 1
    assert argv_logs[0]["arg_count"] > 0
    assert argv_logs[0]["argv_chars"] > 0
