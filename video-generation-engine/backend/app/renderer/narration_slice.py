"""Cut one scene's decoded range out of a batched TTS response (RV-Q10).

Writes PCM/WAV, not MP3. The first version of this module cut with
`atrim` (sample-exact on decoded PCM) and then RE-ENCODED the slice to
MP3 on the theory that the render mux only consumes `.mp3` files and a
second lame pass was an acceptable cost. ⚠ The review that prompted this
(§16.1) reported the MP3 round-trip drifting +20/+10/+8ms per slice and
called it blocking. **That was a broken measurement, corrected the same
day**: it decoded slices through `ffmpeg -i pipe:0`, and a piped MP3
decode does not apply the LAME/Xing gapless header, so it counts the
encoder delay and padding as real audio (+24.37ms on the source file
alone). Measured properly, from file paths, the MP3 round-trip drifts
**+0.62ms across four slices** — negligible.

PCM is kept anyway, for robustness rather than as a bug fix. It is
sample-exact *by construction*; the MP3 path's accuracy depends entirely
on every future consumer decoding with gapless metadata applied, which
is one refactor — or one piped decode — away from silently not
happening. That is a thin thing to rest the duration-preserving
invariant on (`docs/plans/output_quality_pass.md` §2.3), given
`app/renderer/audio.py` already records what MP3 framing did to this
codebase once (+145ms over five boundaries).

Nothing downstream cares about the container: `mux_narration`'s concat
FILTER decodes every input to PCM before joining (that is the whole
reason it uses the filter and not the concat demuxer), so a `.wav` input
is exactly as usable as a `.mp3` one. The only cost is size (roughly 5x
the bytes for the same clip, since PCM is uncompressed) — cheap relative
to correctness for a file that lives only long enough to be muxed once.
"""

import tempfile
from pathlib import Path

from app.core.errors import PermanentError
from app.renderer.slideshow import run_ffmpeg


async def slice_wav(
    content: bytes,
    start_s: float,
    end_s: float,
    *,
    ffmpeg_binary: str,
) -> bytes:
    """Return the `[start_s, end_s)` region of `content` as PCM/WAV.

    `atrim` operates on decoded samples (same reason `mux_narration`
    uses the concat filter, not the concat demuxer). Sample rate is
    pinned to 44100 to match `elevenlabs_output_format = mp3_44100_128`.
    Encoding to `pcm_s16le`/`.wav` instead of re-encoding to MP3 is what
    keeps the cut sample-exact — see the module docstring for the
    measured numbers.
    """
    duration = end_s - start_s
    if duration <= 0:
        raise PermanentError(
            f"narration slice has non-positive duration ({start_s:.3f}s .. {end_s:.3f}s)"
        )
    with tempfile.TemporaryDirectory() as tmp:
        src_path = Path(tmp) / "src.mp3"
        dst_path = Path(tmp) / "dst.wav"
        src_path.write_bytes(content)
        await run_ffmpeg(
            [
                ffmpeg_binary,
                "-y",
                "-i",
                str(src_path),
                "-af",
                f"atrim=start={start_s:.6f}:end={end_s:.6f},asetpts=PTS-STARTPTS",
                "-c:a",
                "pcm_s16le",
                "-ar",
                "44100",
                str(dst_path),
            ]
        )
        return dst_path.read_bytes()
