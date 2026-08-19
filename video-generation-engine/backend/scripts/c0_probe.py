"""C0 — the encode probe (docs/plans/track_c_long_form_video.md, §4.1/§11 Q1).

Builds a ~185-shot Timeline directly in Python (no LLM call, no asset
resolution, no DB, no spend) and renders it through the real, unmodified
`render_timeline`, twice:

  1. "motion"  — a realistic mix of Ken Burns camera movements (SLOW_ZOOM,
     SLOW_PUSH, PULL_BACK, PAN, PUNCH_IN), the case real archival footage
     almost always hits.
  2. "static"  — every shot's `camera` forced to the STATIC default,
     everything else (images, durations, transitions) identical.

Every shot is DISSOLVE-joined to the next (except the last, which is a
CUT so the timeline ends cleanly) — `group_into_runs` therefore produces
exactly ONE run of ~185 shots, the dissolve-heavy worst case §4.3
identifies as having no run-level parallelism available. This also means
each variant makes exactly one `run_ffmpeg` call, so that call's argv
IS the full-length argv this probe exists to measure (closes Q7).

The difference between (1) and (2)'s wall-clock time is the zoompan
multiplier — never measured before this probe (§4.1).

Run inside the real `backend/Dockerfile` container (Linux), not on
Windows — Windows' `CreateProcess` argv limit (32,767 chars) is a
separate, already-diagnosed failure (§4.2) that this probe will also
hit at ~185 shots if run natively on Windows; that is expected and
does not invalidate the timing measurement, only the argv-length one.

    docker compose run --rm backend python scripts/c0_probe.py

Real archival-style photos already on disk (hinglish_final_project's
fixture media — full-resolution JPGs, not placeholders) are cycled
across all 185 shots; asset variety is explicitly out of scope for C0
(§11 Q1). Sourced from `tests/fixtures/`, not `storage/`, deliberately:
`docker-compose.yml` mounts a named volume over `/app/storage`, which
shadows the host's `backend/storage/` bind mount inside the container —
`tests/fixtures/` has no such overlay.
"""

import asyncio
import json
import platform
import resource
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))

from app.core.config import settings  # noqa: E402
from app.renderer import slideshow  # noqa: E402
from app.renderer.slideshow import RenderSettings, render_timeline  # noqa: E402
from app.schemas.timeline import (  # noqa: E402
    Camera,
    CameraDirection,
    CameraMovement,
    ProducedBy,
    Scene,
    Shot,
    ShotIntent,
    Timeline,
    TimelineStatus,
    Transition,
    TransitionType,
)

ASSET_DIRS = [
    _BACKEND / "tests" / "fixtures" / "hinglish_final_project_media" / "assets",
    _BACKEND / "tests" / "fixtures" / "hinglish_final_project_media" / "clips",
]
PROBE_DIR = _BACKEND / "storage" / "_c0_probe"

N_SHOTS = 185
N_SCENES = 65
DISSOLVE_S = 0.5
DURATIONS = [2.5, 3.0, 3.5, 4.0, 3.2]  # cycled; ~592s (~9.9 min) of output over 185 shots
MOVEMENTS = [
    (CameraMovement.SLOW_ZOOM, CameraDirection.IN),
    (CameraMovement.SLOW_PUSH, CameraDirection.NONE),
    (CameraMovement.PULL_BACK, CameraDirection.NONE),
    (CameraMovement.PAN, CameraDirection.LEFT),
    (CameraMovement.PAN, CameraDirection.RIGHT),
    (CameraMovement.PUNCH_IN, CameraDirection.NONE),
]

_RENDER_SETTINGS = RenderSettings(
    width=settings.render_width,
    height=settings.render_height,
    fps=settings.render_fps,
    pixel_format=settings.render_pixel_format,
    ffmpeg_binary=settings.ffmpeg_binary,
    ffprobe_binary=settings.ffprobe_binary,
)


class FfmpegRecorder:
    """Wraps the real `run_ffmpeg` to capture wall-clock time, argv size,
    and peak child RSS per invocation, without changing what it does.
    Assigning over `slideshow.run_ffmpeg` works because `_render_run`/
    `render_timeline` resolve that name from the module's own globals at
    call time.

    Peak RSS via `RUSAGE_CHILDREN` (§12 step 9a's memory-hypothesis
    test): Linux's `getrusage(2)` reports `ru_maxrss` for terminated
    children as a running high-water mark, not a sum — so as long as
    each probe invocation makes exactly one `run_ffmpeg` call (true here:
    dissolve-heavy -> one run -> one ffmpeg process), the value read
    immediately after that call IS that process's peak resident set,
    with no extra tooling (`/usr/bin/time`, `docker stats`) needed."""

    def __init__(self, original):
        self._original = original
        self.calls: list[dict] = []

    async def __call__(self, args: list[str]) -> None:
        start = time.monotonic()
        try:
            await self._original(args)
        finally:
            peak_rss_kb = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
            self.calls.append(
                {
                    "elapsed_s": time.monotonic() - start,
                    "arg_count": len(args),
                    "argv_chars": len(" ".join(args)),
                    "peak_rss_kb": peak_rss_kb,
                }
            )


def _real_photos() -> list[Path]:
    photos = sorted(
        p
        for d in ASSET_DIRS
        for p in d.iterdir()
        if p.suffix.lower() in (".jpg", ".jpeg", ".webp", ".png")
    )
    if not photos:
        raise SystemExit(f"no real photos found under {ASSET_DIRS}")
    return photos


def build_timeline(camera_mode: str) -> tuple[Timeline, dict[str, Path]]:
    if camera_mode not in ("motion", "static"):
        raise ValueError(camera_mode)
    photos = _real_photos()

    shots: list[Shot] = []
    shot_images: dict[str, Path] = {}
    for i in range(N_SHOTS):
        shot_id = f"s{i:03d}"
        duration = DURATIONS[i % len(DURATIONS)]
        if camera_mode == "static":
            camera = Camera()  # default movement=STATIC
        else:
            movement, direction = MOVEMENTS[i % len(MOVEMENTS)]
            camera = Camera(movement=movement, direction=direction, intensity=0.2)
        is_last = i == N_SHOTS - 1
        transition = (
            Transition(type=TransitionType.CUT, duration_s=0.0)
            if is_last
            else Transition(type=TransitionType.DISSOLVE, duration_s=DISSOLVE_S)
        )
        shots.append(
            Shot(
                id=shot_id,
                order=i,
                intent=ShotIntent.EXPLAIN,
                duration_s=duration,
                camera=camera,
                transition_out=transition,
            )
        )
        shot_images[shot_id] = photos[i % len(photos)]

    base, remainder = divmod(N_SHOTS, N_SCENES)
    scenes: list[Scene] = []
    idx = 0
    for scene_idx in range(N_SCENES):
        count = base + (1 if scene_idx < remainder else 0)
        scene_shots = shots[idx : idx + count]
        scenes.append(
            Scene(
                id=f"sc{scene_idx:03d}",
                order=scene_idx,
                title=f"Scene {scene_idx}",
                duration_s=sum(s.duration_s for s in scene_shots),
                shots=scene_shots,
            )
        )
        idx += count
    assert idx == N_SHOTS

    timeline = Timeline(
        timeline_id="c0-probe",
        project_id="c0-probe-project",
        version=1,
        produced_by=ProducedBy.HUMAN,
        status=TimelineStatus.DRAFT,
        created_at=datetime.now(UTC),
        scenes=scenes,
    )
    return timeline, shot_images


async def run_static_altinput_variant() -> dict:
    """§12 step 9a's memory-hypothesis test, isolated: the SAME 185 shots,
    images, durations, and dissolve transitions as the `static` variant,
    but with a different input shape for ffmpeg. `_render_run`'s static
    path decodes each still via `-loop 1 -t <duration> -i <path>` (a
    demuxer-level loop that generates duplicate frames on read); this
    variant instead single-decodes (`-i <path>`, exactly what a Ken-Burns
    shot already gets) and holds that one frame for the shot's duration
    with `tpad=stop_mode=clone` inside the filtergraph — the same
    "one decode, generate duration internally" shape `zoompan`'s own `d=`
    parameter already uses for motion shots. If peak RSS drops sharply
    against the real `static` variant's measured number, the OOM's cause
    is confirmed as input shape (a `_render_run` fix), not filter cost or
    a production memory ceiling — this is deliberately NOT wired through
    `render_timeline`/`_render_run`, since testing an input shape those
    functions don't produce for any real `Shot`/`Camera` combination
    requires a standalone ffmpeg invocation, reusing only the parts of
    `_render_run`'s logic (frame-count arithmetic, xfade chaining) that
    aren't the variable under test."""
    from app.renderer.slideshow import run_ffmpeg as _run_ffmpeg_unwrapped

    timeline, shot_images = build_timeline("static")
    shots = timeline.all_shots()
    output_path = PROBE_DIR / "output_static_altinput.mp4"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    w, h, fps, pf = (
        _RENDER_SETTINGS.width,
        _RENDER_SETTINGS.height,
        _RENDER_SETTINGS.fps,
        _RENDER_SETTINGS.pixel_format,
    )
    args = [_RENDER_SETTINGS.ffmpeg_binary, "-y"]
    frame_counts = [max(round(shot.duration_s * fps), 1) for shot in shots]
    for shot in shots:
        args += ["-i", str(shot_images[shot.id])]

    filters: list[str] = []
    labels: list[str] = []
    for i, (shot, frames) in enumerate(zip(shots, frame_counts, strict=True)):
        label = f"n{i}"
        hold_s = frames / fps
        filters.append(
            f"[{i}:v]scale={w}:{h}:force_original_aspect_ratio=decrease,"
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,"
            f"tpad=stop_mode=clone:stop_duration={hold_s:.6f},"
            f"fps={fps},format={pf}[{label}]"
        )
        labels.append(label)

    cumulative = shots[0].duration_s
    prev_label = labels[0]
    for i in range(1, len(shots)):
        overlap = shots[i - 1].transition_out.duration_s
        transition_name = shots[i - 1].transition_out.type.value
        offset = max(cumulative - overlap, 0.0)
        out_label = f"x{i}"
        filters.append(
            f"[{prev_label}][{labels[i]}]xfade=transition={transition_name}:"
            f"duration={overlap:.3f}:offset={offset:.3f}[{out_label}]"
        )
        cumulative = cumulative + shots[i].duration_s - overlap
        prev_label = out_label

    args += [
        "-filter_complex", ";".join(filters), "-map", f"[{prev_label}]",
        "-r", str(fps), "-fflags", "+bitexact", "-flags:v", "+bitexact",
        "-threads", "1", "-c:v", "libx264", "-pix_fmt", pf,
        "-movflags", "+faststart", str(output_path),
    ]

    recorder = FfmpegRecorder(_run_ffmpeg_unwrapped)
    start = time.monotonic()
    await recorder(args)
    total_wall_s = time.monotonic() - start
    return {
        "camera_mode": "static_altinput",
        "total_wall_s": total_wall_s,
        "n_runs": len(recorder.calls),
        "runs": recorder.calls,
        "output_path": str(output_path),
        "output_bytes": output_path.stat().st_size if output_path.exists() else None,
    }


async def run_variant(camera_mode: str) -> dict:
    timeline, shot_images = build_timeline(camera_mode)
    work_dir = PROBE_DIR / f"work_{camera_mode}"
    output_path = PROBE_DIR / f"output_{camera_mode}.mp4"

    original_run_ffmpeg = slideshow.run_ffmpeg
    recorder = FfmpegRecorder(original_run_ffmpeg)
    slideshow.run_ffmpeg = recorder
    try:
        start = time.monotonic()
        await render_timeline(
            timeline, shot_images, _RENDER_SETTINGS, output_path, work_dir=work_dir
        )
        total_wall_s = time.monotonic() - start
    finally:
        slideshow.run_ffmpeg = original_run_ffmpeg

    return {
        "camera_mode": camera_mode,
        "total_wall_s": total_wall_s,
        "n_runs": len(recorder.calls),
        "runs": recorder.calls,
        "output_path": str(output_path),
        "output_bytes": output_path.stat().st_size if output_path.exists() else None,
    }


async def main() -> None:
    PROBE_DIR.mkdir(parents=True, exist_ok=True)
    print(f"platform: {platform.system()} {platform.release()}")
    if platform.system() != "Linux":
        print(
            "WARNING: not running on Linux — timing is still informative, but the "
            "argv-length measurement below only settles Q7/§4.2 when run inside "
            "the real backend/Dockerfile container."
        )
    print(f"shots={N_SHOTS} scenes={N_SCENES} resolution={_RENDER_SETTINGS.width}x"
          f"{_RENDER_SETTINGS.height} fps={_RENDER_SETTINGS.fps}")
    print()

    report_path = PROBE_DIR / "report.json"
    results = {}
    if report_path.exists():
        # Resume-friendly: a prior run's variant(s) already succeeded and
        # are expensive (~16 min each) — don't re-pay for them.
        existing = json.loads(report_path.read_text(encoding="utf-8"))
        results = existing.get("results", {})

    modes = sys.argv[1:] or ["motion", "static"]
    for mode in modes:
        if mode in results:
            print(f"--- skipping variant: {mode} (already in {report_path.name}) ---")
            continue
        print(f"--- rendering variant: {mode} ---", flush=True)
        result = (
            await run_static_altinput_variant()
            if mode == "static_altinput"
            else await run_variant(mode)
        )
        results[mode] = result
        for run in result["runs"]:
            print(
                f"  run: {run['elapsed_s']:.1f}s encode, "
                f"{run['arg_count']} args, {run['argv_chars']} argv chars, "
                f"peak RSS {run['peak_rss_kb'] / 1024 / 1024:.2f} GB",
                flush=True,
            )
        print(f"  total wall clock (incl. probing/normalising): {result['total_wall_s']:.1f}s")
        print()
        report_path.write_text(json.dumps({"results": results}, indent=2), encoding="utf-8")

    print("=== summary ===")
    multiplier = None
    if "motion" in results:
        print(f"motion (Ken Burns mix) wall clock: {results['motion']['total_wall_s']:.1f}s")
    if "static" in results:
        print(f"static wall clock:                 {results['static']['total_wall_s']:.1f}s")
    if "motion" in results and "static" in results and results["static"]["total_wall_s"]:
        multiplier = results["motion"]["total_wall_s"] / results["static"]["total_wall_s"]
        print(f"zoompan multiplier (motion/static): {multiplier:.2f}x")
    motion_argv = (
        results.get("motion", {}).get("runs", [None])[0] if results.get("motion") else None
    )
    if motion_argv:
        print(
            f"argv at {N_SHOTS} shots, one run: {motion_argv['arg_count']} args, "
            f"{motion_argv['argv_chars']} chars (Windows CreateProcess limit: 32767)"
        )
    if "static" in results and "static_altinput" in results:
        static_rss = results["static"]["runs"][0]["peak_rss_kb"] / 1024 / 1024
        alt_rss = results["static_altinput"]["runs"][0]["peak_rss_kb"] / 1024 / 1024
        print(
            f"\n§12 step 9a memory hypothesis: static (-loop 1 -t) peak RSS "
            f"{static_rss:.2f} GB vs static_altinput (-i + tpad) peak RSS {alt_rss:.2f} GB "
            f"({'CONFIRMED' if alt_rss < static_rss * 0.7 else 'NOT CONFIRMED'} — "
            f"{'input shape is the cause' if alt_rss < static_rss * 0.7 else 'input shape is not the dominant factor'})"
        )

    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "platform": f"{platform.system()} {platform.release()}",
        "n_shots": N_SHOTS,
        "n_scenes": N_SCENES,
        "resolution": [_RENDER_SETTINGS.width, _RENDER_SETTINGS.height],
        "fps": _RENDER_SETTINGS.fps,
        "results": results,
        "zoompan_multiplier": multiplier,
    }
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nwrote {report_path}")


if __name__ == "__main__":
    asyncio.run(main())
