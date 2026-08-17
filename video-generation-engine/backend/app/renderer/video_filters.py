"""The generic post-composition video filter pass (docs/plans/
watermark_implementation_plan.md §1): whatever combination of captions
and watermark is enabled, it runs as ONE ffmpeg re-encode over the
silent-composed video, never one pass per filter.

Why one pass, not one per filter: `subtitles=` and `overlay=` both
require re-encoding (`-c:v copy` cannot run through either). Renamed out
of `captions.py` when the watermark plan generalised the caption-only
burn pass into "the video filter pass" - `app/renderer/captions.py` and
`app/renderer/watermark.py` each build their own filter_complex FRAGMENT
referencing an input/output label; this module only knows how to run
ffmpeg over whatever fragments the caller composed, not what any
fragment means.
"""

from pathlib import Path

from app.renderer.slideshow import RenderSettings, run_ffmpeg


def escape_ffmpeg_filter_path(path: Path) -> str:
    """Windows path escaping for filter arguments that embed a filesystem
    path (`subtitles=`, `fontsdir=` - flagged as a known trap in
    docs/13_Implementation_Guide.md's own day-one advice): forward-slash
    the path (ffmpeg filter argument parsing chokes on backslashes) then
    escape the drive-letter colon, which the filter's own `key=value`
    grammar would otherwise read as a parameter separator - `C:/x` must
    become `C\\:/x`. Verified empirically (not just per the docs) against
    a real ffmpeg invocation: the escaped colon ALONE is not sufficient
    once a second colon-bearing option (`fontsdir=`) is chained after it
    in the same filter string - the caller must also wrap each escaped
    path in single quotes (`filename='C\\:/x':fontsdir='C\\:/y'`), or
    ffmpeg's filtergraph parser misreads where the first value ends."""
    posix = path.resolve().as_posix()
    return posix.replace(":", "\\:")


async def apply_video_filters(
    video_path: Path,
    output_path: Path,
    settings: RenderSettings,
    *,
    extra_inputs: list[Path],
    filter_complex: str,
    output_label: str,
) -> Path:
    """Runs `filter_complex` over `video_path` (always input `0`) plus
    any `extra_inputs` (the watermark logo, at whatever index the caller
    referenced when building its fragment), mapping `output_label` to the
    output file. Mirrors `slideshow.py::_render_run`'s exact deterministic
    libx264 recipe (I5: `+bitexact`, single-threaded) since this is the
    other place in the pipeline that re-encodes video."""
    args = [settings.ffmpeg_binary, "-y", "-i", str(video_path)]
    for path in extra_inputs:
        args += ["-i", str(path)]
    args += [
        "-filter_complex",
        filter_complex,
        "-map",
        f"[{output_label}]",
        "-fflags",
        "+bitexact",
        "-flags:v",
        "+bitexact",
        "-threads",
        "1",
        "-c:v",
        "libx264",
        "-pix_fmt",
        settings.pixel_format,
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    await run_ffmpeg(args)
    return output_path
