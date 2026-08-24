"""Deterministic narration pacing, independent of whatever a TTS
provider's own speed knob does or doesn't do (2026-08-24).

`eleven_multilingual_v2`'s `voice_settings.speed` scaled duration
cleanly (R8, live-checked). `eleven_v3` does not: a live check
(`r8_speed_probe.py`-style, done while diagnosing a `retention_fast`
project sounding too slow) sent `speed` values from 0.5 to 3.0 against
the same text and got durations with NO monotonic relationship to the
requested value at all - not "weaker", genuinely non-functional for
this parameter on this model. ElevenLabs' own docs confirm v3 moved
pacing control into the text itself (audio tags, punctuation), not a
numeric multiplier - which cannot serve this codebase's duration
reconciliation (D1) the way a precise, requestable multiplier can.

So pacing is applied HERE instead, once, via ffmpeg's `atempo` filter on
the already-synthesised audio - correct regardless of which model or
provider produced it, forever. The ElevenLabs alignment is rescaled by
the exact same factor so captions and shot durations (both keyed off
`character_end_times_seconds`) describe the STRETCHED audio's real
timeline, not the original's. Provider-side `voice_settings.speed` is no
longer sent at all (see `providers/elevenlabs.py`) - sending it AND
applying this would double the effect on any model where it actually
does work.

ffmpeg's `atempo` accepts 0.5-2.0 per instance; `canonical_narration_speed`
(R8) never asks for a factor outside 0.7-1.2, so this never needs to
chain multiple `atempo` stages.
"""

import tempfile
from pathlib import Path

from app.renderer.slideshow import run_ffmpeg


async def apply_narration_tempo(
    content: bytes,
    alignment: dict,
    factor: float,
    *,
    ffmpeg_binary: str,
) -> tuple[bytes, dict]:
    """Speeds up (`factor` > 1.0) or slows down (`factor` < 1.0) `content`
    - encoded MP3 bytes - by exactly `factor`, and rescales `alignment`'s
    two timing arrays by the same factor so they still describe the
    OUTPUT audio's real timeline.

    `factor == 1.0` is a no-op passthrough - no ffmpeg call, no
    re-encode - the common case for every style except retention_fast.
    """
    if factor == 1.0:
        return content, alignment

    with tempfile.TemporaryDirectory() as tmp:
        src_path = Path(tmp) / "src.mp3"
        dst_path = Path(tmp) / "dst.mp3"
        src_path.write_bytes(content)
        await run_ffmpeg(
            [
                ffmpeg_binary,
                "-y",
                "-i",
                str(src_path),
                "-filter:a",
                f"atempo={factor}",
                "-c:a",
                "libmp3lame",
                "-b:a",
                "128k",
                str(dst_path),
            ]
        )
        new_content = dst_path.read_bytes()

    new_alignment = dict(alignment)
    new_alignment["character_start_times_seconds"] = [
        t / factor for t in alignment.get("character_start_times_seconds", [])
    ]
    new_alignment["character_end_times_seconds"] = [
        t / factor for t in alignment.get("character_end_times_seconds", [])
    ]
    return new_content, new_alignment
