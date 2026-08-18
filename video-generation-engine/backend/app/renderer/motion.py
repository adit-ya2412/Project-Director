"""Classify a shot's resolved media as a still image or a real motion
clip (motion_new_styles_and_long_form_videos.md, Track A, A1) - the
decision `app/renderer/slideshow.py::render_timeline` uses to choose
between the existing `-loop 1 -t duration` still path and a new
motion-clip input branch, and to fit a clip's real duration to the
shot's `duration_s` (A2).

## The classification rule, and why it isn't simpler

Pillow OPENS the file -> STILL. Pillow correctly identifies every format
this renderer already knew how to loop or flatten - JPEG/PNG/BMP/TIFF
loop directly, and an animated GIF (`is_animated=True`) is flattened to
its first frame by `app/renderer/still.py`, existing behaviour this
classifier must preserve bit-for-bit (Commons serves plenty of GIF maps
and process diagrams `app/assets/validation.py` deliberately accepts).

Pillow FAILS to open it -> ffprobe must then POSITIVELY CONFIRM a real
video stream with a positive duration before this is ever called MOTION.
A Pillow failure alone is only evidence of "not a still Pillow
understands" (a corrupt file fails identically) - never evidence of
motion. Anything that fails BOTH checks falls back to STILL, matching
`still.py`'s own existing fallback ("not something Pillow reads... let
the converter take its first frame") - unchanged behaviour for the one
case nobody has ever seen but must not crash the render.

See the plan's own A1 correction (2026-08-18): the original wording
("classify by ffprobe, not by asking Pillow") would have misclassified
every animated GIF as motion, breaking the flattening behaviour above.
"""

import asyncio
import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from PIL import Image


class MediaKind(Enum):
    STILL = "still"
    MOTION = "motion"


@dataclass(frozen=True)
class MediaProbe:
    kind: MediaKind
    # Only set when kind is MOTION - the real, ffprobe-measured duration
    # of the confirmed video stream, reused directly by the A2 duration-
    # fit arithmetic below so classification never costs a second ffprobe
    # call just to learn the same number again.
    duration_s: float | None = None


async def probe_media(path: Path, *, ffprobe_binary: str = "ffprobe") -> MediaProbe:
    try:
        with Image.open(path):
            pass
        return MediaProbe(kind=MediaKind.STILL)
    except (OSError, ValueError):
        pass

    duration_s = await _confirmed_video_duration(path, ffprobe_binary=ffprobe_binary)
    if duration_s is None:
        return MediaProbe(kind=MediaKind.STILL)
    return MediaProbe(kind=MediaKind.MOTION, duration_s=duration_s)


async def _confirmed_video_duration(path: Path, *, ffprobe_binary: str) -> float | None:
    """`None` unless ffprobe finds a genuine video stream AND a positive
    duration for it - either signal alone is not enough (a container with
    a video stream but no readable duration cannot be duration-fitted by
    A2; a readable duration with no video stream is not a video at all)."""
    args = [
        ffprobe_binary,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=codec_type,duration:format=duration",
        "-of",
        "json",
        str(path),
    ]
    process = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, _stderr = await process.communicate()
    if process.returncode != 0:
        return None
    try:
        data = json.loads(stdout.decode())
    except json.JSONDecodeError:
        return None

    streams = data.get("streams") or []
    if not streams or streams[0].get("codec_type") != "video":
        return None

    # Some codecs/containers leave the STREAM-level duration unset even
    # though the video is real - fall back to the container-level FORMAT
    # duration in that case rather than reporting no duration at all.
    raw_duration = streams[0].get("duration") or (data.get("format") or {}).get("duration")
    if raw_duration is None:
        return None
    try:
        duration = float(raw_duration)
    except (TypeError, ValueError):
        return None
    return duration if duration > 0 else None


# --- A2: duration reconciliation for a motion clip -------------------

# Below this gap, in seconds, the mismatch is not worth a filter stage at
# all - narrower than a single frame at any fps this renderer supports.
_FIT_TOLERANCE_S = 0.02


def build_duration_fit_fragment(
    *, actual_duration_s: float, target_duration_s: float
) -> str | None:
    """The one function A2's arithmetic lives in (D5's own "compute it
    once" discipline, applied here too). Narration is the master clock;
    Kling returns a fixed length close to, but never exactly, the shot's
    `duration_s`. `None` means the gap is negligible and no filter stage
    is needed at all.

    DECIDED 2026-08-18 (Q4): a too-long clip is TRIMMED; a too-short clip
    HOLDS ITS LAST FRAME (`tpad=stop_mode=clone`) rather than looping or
    slowing down - looping reads as a glitch, and slow motion changes the
    footage's character while fighting fps normalisation. Put to the user
    with real numbers from the `m8_test_project` fixture rather than as
    an abstract preference: because `fal_video.py` asks Kling for
    `round(shot.duration_s)`, the gap this ever needs to cover is
    mathematically bounded at +-0.5s, and measuring every shot in that
    fixture found the worst case was +0.50s, with 6 of 8 affected shots'
    held tails falling entirely inside their own outgoing dissolve.

    Either branch is built to emit EXACTLY `target_duration_s` seconds of
    output, so the caller's existing `xfade` offset arithmetic (D5) keeps
    working untouched - getting this wrong desynchronises audio from
    picture progressively and presents as a mystery, not as a transition
    bug (see `app/renderer/slideshow.py`'s own docstring, A1's pitfalls)."""
    gap = target_duration_s - actual_duration_s
    if abs(gap) < _FIT_TOLERANCE_S:
        return None
    if gap < 0:
        return f"trim=duration={target_duration_s:.3f},setpts=PTS-STARTPTS"
    return f"tpad=stop_mode=clone:stop_duration={gap:.3f}"
