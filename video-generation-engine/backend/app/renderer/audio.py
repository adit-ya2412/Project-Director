"""Narration muxing: the M8 step-3 audio pass (implementation guide, Phase
M8, build order item 3 — "Mux narration into the render").

The visual composition path (`app/renderer/slideshow.py`) is untouched by
this module: narration is added as ONE final ffmpeg pass over its already
-finished silent output, never threaded through the per-run xfade graph.
Doing it any other way would recreate, for audio, exactly the drift D5
exists to prevent for video — an xfade's overlap subtracts real seconds
from the picture's timeline, so feeding raw per-scene audio through that
same graph would mean re-deriving D5's overlap arithmetic a second time,
in a second place, for a second medium (the "duplicating this logic
anywhere else" trap `app/timeline/duration.py`'s own docstring warns
about). Keeping the mux separate means the video graph, already proven,
needs no changes at all — see `RenderStep` for how the two passes compose.

## The concatenation trap — MP3 specifically

Per-scene narration audio is stored as MP3 (`elevenlabs_output_format`,
e.g. `mp3_44100_128`). MP3 is a FRAMED codec with encoder delay and
padding around every encoded stream, so joining encoded MP3 byte streams
end to end — ffmpeg's concat DEMUXER, or a raw byte concatenation — does
NOT reproduce "these clips played back to back": every boundary loses or
gains a few milliseconds depending on where the frame grid falls. On a
multi-scene video that is several boundaries of small, compounding error
— the audio drifts progressively later against the picture, and it
presents as "the voice slowly falls behind", not as an obvious concat
bug. Measured empirically while building this module: five MP3s whose
real decoded durations summed to 5.420998s came out to 5.565828s through
the concat demuxer (+145ms — about 36ms per boundary, and growing with
every scene) and exactly 5.420998s through the approach below. See
`tests/integration/test_narration_audio_concat.py` for the automated,
numeric version of that same proof.

The fix: use ffmpeg's `concat` FILTER, not the concat demuxer. The filter
operates on DECODED audio samples — every input is fully decoded to PCM
before joining, so "joining" is just placing sample buffers back to back
on the sample timeline. There is no encoder framing left at the boundary
to lose or pad, so the joined track's duration is exactly the sum of the
inputs' true decoded durations, by construction, regardless of how many
scenes are joined.
"""

from pathlib import Path

from app.core.errors import PermanentError
from app.renderer.slideshow import RenderSettings, run_ffmpeg


async def mux_narration(
    video_path: Path,
    narration_paths: list[Path],
    output_path: Path,
    settings: RenderSettings,
) -> Path:
    """Decode-and-concatenate `narration_paths` (already in Timeline scene
    order — ordering is the caller's responsibility, the same contract
    `render_timeline` already has for `shot_images`) via the concat filter,
    then mux the joined track onto `video_path`, writing `output_path`.

    Video is stream-copied (`-c:v copy`) — its bytes are already correct
    and this pass must not re-encode or otherwise touch them. The joined
    narration is encoded once, to AAC, the codec an MP4/`+faststart`
    container expects; re-encoding audio here is unavoidable (the concat
    filter's output is raw decoded samples) but happens exactly once, not
    once per scene boundary.

    Deliberately NO `-shortest`. `render_timeline`'s video is quantised to
    whole frames (each shot's `-t` duration gets re-timed onto
    `settings.fps`), so its true rendered length can land a few
    milliseconds either side of the narration's exact sum — measured
    empirically while building this: a 4-shot/4.153016s narrated timeline
    rendered to a 4.133333s silent video, ~20ms short. `-shortest` would
    have silently clipped that ~20ms off the END of the real, correct
    narration to match — which is exactly the "truncating audio is not an
    option; it cuts words off mid-sentence" the M8 design decisions rule
    out, just at a duration small enough to look tempting. Narration is
    the master clock (D1): it keeps its full, true length regardless of
    which way the video's frame quantisation happens to round, and any
    sub-frame gap between the two streams' reported durations is the
    video's rounding, not the audio's problem to absorb.
    """
    if not narration_paths:
        raise PermanentError("mux_narration called with no narration audio to mux")

    args = [settings.ffmpeg_binary, "-y", "-i", str(video_path)]
    for path in narration_paths:
        args += ["-i", str(path)]

    n = len(narration_paths)
    # Deterministic label order (I5): built from range(n), never a dict or
    # set, so the concat order is always exactly Timeline scene order.
    audio_labels = "".join(f"[{i + 1}:a]" for i in range(n))
    filter_complex = f"{audio_labels}concat=n={n}:v=0:a=1[aout]"

    args += [
        "-filter_complex",
        filter_complex,
        "-map",
        "0:v",
        "-map",
        "[aout]",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        # I5 (M8 step 6): strip non-deterministic muxer/encoder metadata
        # so the same inputs always produce the same output bytes - see
        # app/renderer/slideshow.py's own comment on this exact pair.
        "-fflags",
        "+bitexact",
        "-flags:a",
        "+bitexact",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    await run_ffmpeg(args)
    return output_path
