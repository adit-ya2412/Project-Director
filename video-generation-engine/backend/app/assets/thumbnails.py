"""On-demand, cached image bytes for the browser (M9, F0b).

`asset.local_path`, `generated_clip.local_path`, and `project.video_path`
are all server filesystem paths - nothing before this module ever serves
their actual bytes over HTTP, so a browser cannot display an approval-
gate image (`GET /projects/{id}/shots/{shot_id}/asset`) or a project-list
thumbnail (`GET /projects/{id}/thumbnail`) at all. Both endpoints
(`app/api/projects.py`) share the identical underlying shape: a SOURCE
file on disk that is either already a still image, or a video whose one
representative frame is wanted - and this module owns turning the second
case into the first, cached, so it is only ever done once per source
version.

## Why cache at all, and why lazily

A frame extraction is a real ffmpeg subprocess (decode up to the target
timestamp, emit one frame) and a resize is a real decode+re-encode - both
cheap individually but wasteful to repeat on every request for a project
whose list card gets re-rendered on every poll. Lazily, on first request,
because eager generation (e.g. at render time) would do this work for
every project whether or not a human ever opens it - most of the cost
this cache exists to avoid.

## Why the source's mtime, not a content hash

A content hash would need to read (and for a video, decode) the WHOLE
source file just to decide whether the cache is still valid - exactly
the cost this cache exists to avoid paying on every request. The
source's own mtime is what every OTHER staleness check in this codebase
already keys on for the identical reason: `RenderStep.is_satisfied`
compares a `shot_binding` row's `updated_at` against the rendered file's
own mtime specifically because "the file exists" was already proven not
to be enough (see that module's docstring on the stale-cache bug it
shipped once - a resolved-then-re-resolved shot silently kept serving
the OLD render). A thumbnail cache with no invalidation at all would
reproduce the identical bug one layer up: a re-render with a new voice
replaces `final.mp4` in place, and without an mtime check the project
list would keep showing the OLD video's frame forever. `cache mtime <
source mtime` means the source changed since the cache was written and
the cache is regenerated; otherwise it is served as-is, with no read of
the source's own bytes at all.
"""

from pathlib import Path

from PIL import Image

from app.renderer.slideshow import probe_duration_seconds, run_ffmpeg

# Suffixes the pipeline itself actually writes for VIDEO media -
# `generated_clip.local_path` for an image-to-video generation (rung 5,
# `app/workflow/steps/resolve_assets.py::_generate_video_real`) and
# `project.video_path`/the draft endpoint's own output for the renderer's
# own `final.mp4`/`draft.mp4`. Anything else this module is ever handed is
# a still image - a narrower, purely extension-based question than
# `app/renderer/still.py::needs_normalising` answers (that module cares
# whether ffmpeg can `-loop` a file; this one only cares whether a frame
# needs extracting from it at all).
_VIDEO_SUFFIXES = frozenset({".mp4", ".mov", ".webm", ".mkv"})

# Roughly 10% into a video, clamped to [0.5s, 3s] (F1) - never frame 0,
# which is routinely a fade-in or a dark frame on a real render.
_FRAME_FRACTION = 0.1
_FRAME_MIN_S = 0.5
_FRAME_MAX_S = 3.0

# The longest edge a resized still/extracted frame is allowed to keep -
# generous enough for a full-screen approval-gate image, small enough
# that a project-list page full of cards never ships full-resolution
# archival photographs to the browser.
_MAX_DIMENSION = 640


def is_video_file(path: Path) -> bool:
    return path.suffix.lower() in _VIDEO_SUFFIXES


def _cache_is_fresh(source: Path, cache: Path) -> bool:
    return cache.exists() and cache.stat().st_mtime >= source.stat().st_mtime


def _frame_timestamp(duration_s: float) -> float:
    """Roughly 10% in, clamped to [0.5s, 3s] (F1) - and additionally never
    past the clip's own end, which the [0.5s, 3s] floor alone cannot
    guarantee for a clip shorter than half a second (a real case: a
    single-shot generated clip, not just a full render)."""
    target = min(max(duration_s * _FRAME_FRACTION, _FRAME_MIN_S), _FRAME_MAX_S)
    return min(target, max(duration_s - 0.05, 0.0))


async def cached_video_frame(
    video_path: Path,
    cache_path: Path,
    *,
    ffmpeg_binary: str,
    ffprobe_binary: str,
) -> Path:
    """A JPEG frame from `video_path`, written to `cache_path` and reused
    across requests until `video_path`'s own mtime moves past it (see this
    module's docstring). `video_path` itself is never modified."""
    if _cache_is_fresh(video_path, cache_path):
        return cache_path

    duration = await probe_duration_seconds(video_path, ffprobe_binary)
    at_second = _frame_timestamp(duration)
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    # `-ss` before `-i` (input seeking) so ffmpeg decodes only up to the
    # target timestamp rather than the whole file first - the same
    # tradeoff every other single-frame extraction in this codebase makes
    # (see `app/renderer/still.py::ensure_still_image`, though that one
    # always wants frame 0 and so has no `-ss` to place at all).
    await run_ffmpeg(
        [
            ffmpeg_binary,
            "-y",
            "-ss",
            f"{at_second:.3f}",
            "-i",
            str(video_path),
            "-frames:v",
            "1",
            "-update",
            "1",
            str(cache_path),
        ]
    )
    return cache_path


def cached_resized_image(source_path: Path, cache_path: Path) -> Path:
    """A JPEG copy of `source_path`, downscaled so its longest edge is at
    most `_MAX_DIMENSION` (`Image.thumbnail` never upscales - a source
    already smaller is copied through unchanged in content, just
    re-encoded). Cached exactly like `cached_video_frame`, keyed on the
    same mtime comparison."""
    if _cache_is_fresh(source_path, cache_path):
        return cache_path

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source_path) as image:
        rendered = image.convert("RGB")
        rendered.thumbnail((_MAX_DIMENSION, _MAX_DIMENSION))
        rendered.save(cache_path, format="JPEG")
    return cache_path
