"""Real ffmpeg proof that burning captions doesn't break I5: the same
Timeline + narration + cues must produce byte-identical output across two
independent, from-scratch runs - exactly `test_render_determinism.py`'s
own proof, extended to cover the video filter pass (`app/renderer/
video_filters.py::apply_video_filters`, fed a captions-only fragment
here) that re-encodes video instead of stream-copying it.

A real (if synthetic) MP3 is used for narration - not `FakeNarrationProvider`
bytes, which aren't decodable media - following
`test_narration_audio_concat.py`'s own reasoning. The alignment array is
fabricated (uniform per-character timing over the real, MEASURED duration
of the synthesized MP3) since this test proves ENCODER reproducibility,
not cue-timing correctness against real TTS alignment - that's
`tests/unit/renderer/test_captions.py`'s job, against the real fixture.
"""

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image

from app.core.config import settings
from app.renderer.audio import mux_narration
from app.renderer.captions import (
    CaptionStyle,
    FONT_DIR,
    derive_caption_cues,
    serialize_ass,
    subtitles_filter_fragment,
)
from app.renderer.slideshow import RenderSettings, render_timeline
from app.renderer.video_filters import apply_video_filters
from app.models.narration import NarrationModel
from app.schemas.timeline import ProducedBy, Scene, Shot, ShotIntent, Timeline, TimelineStatus
import uuid

_RENDER_SETTINGS = RenderSettings(
    width=320,
    height=240,
    fps=24,
    pixel_format="yuv420p",
    ffmpeg_binary=settings.ffmpeg_binary,
    ffprobe_binary=settings.ffprobe_binary,
    burn_captions=True,
)

_NARRATION_TEXT = "The quick brown fox jumps. Over the lazy dog again."


def _make_image(path: Path, color: tuple[int, int, int]) -> None:
    Image.new("RGB", (320, 240), color).save(path)


def _run(args: list[str]) -> None:
    subprocess.run(args, capture_output=True, check=True)


def _make_sine_mp3(path: Path, duration_s: float) -> None:
    _run(
        [
            settings.ffmpeg_binary, "-y", "-f", "lavfi",
            "-i", f"sine=frequency=440:duration={duration_s}",
            "-ar", "44100", "-b:a", "128k", "-c:a", "libmp3lame", str(path),
        ]
    )


def _stream_duration(path: Path, codec_type: str) -> float:
    args = [
        settings.ffprobe_binary, "-v", "error", "-print_format", "json",
        "-show_entries", "stream=codec_type,duration", str(path),
    ]
    probe = json.loads(subprocess.run(args, capture_output=True, text=True, check=True).stdout)
    for stream in probe["streams"]:
        if stream["codec_type"] == codec_type:
            return float(stream["duration"])
    raise AssertionError(f"no {codec_type} stream in {path}")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _timeline() -> tuple[Timeline, list[NarrationModel]]:
    text = _NARRATION_TEXT
    split = text.index(". ") + 2  # first shot ends after the first sentence
    shots = [
        Shot(
            id="sh_01", order=0, intent=ShotIntent.EXPLAIN, duration_s=2.0,
            narration_span=(0, split),
        ),
        Shot(
            id="sh_02", order=1, intent=ShotIntent.EXPLAIN, duration_s=2.0,
            narration_span=(split, len(text)),
        ),
    ]
    scene = Scene(id="sc_01", order=0, title="Scene", duration_s=4.0, narration_text=text, shots=shots)
    timeline = Timeline(
        timeline_id="t1", project_id="p1", version=1, produced_by=ProducedBy.NARRATION,
        status=TimelineStatus.DRAFT, created_at=datetime(2026, 1, 1, tzinfo=UTC), scenes=[scene],
    )
    return timeline, text


async def _render_captioned_once(tmp_path: Path, suffix: str) -> Path:
    timeline, text = _timeline()
    work_dir = tmp_path / f"work_{suffix}"
    work_dir.mkdir()

    image_a = work_dir / "a.png"
    image_b = work_dir / "b.png"
    _make_image(image_a, (200, 50, 50))
    _make_image(image_b, (50, 50, 200))
    shot_images = {"sh_01": image_a, "sh_02": image_b}

    silent_path = work_dir / "silent.mp4"
    await render_timeline(timeline, shot_images, _RENDER_SETTINGS, silent_path, work_dir=work_dir)

    narration_path = work_dir / "narration.mp3"
    _make_sine_mp3(narration_path, duration_s=4.0)
    measured_duration = _stream_duration(narration_path, "audio")
    n = len(text)
    alignment = {
        "characters": list(text),
        "character_start_times_seconds": [i * measured_duration / n for i in range(n)],
        "character_end_times_seconds": [(i + 1) * measured_duration / n for i in range(n)],
    }
    row = NarrationModel(
        id=uuid.uuid4(), project_id=uuid.uuid4(), scene_id="sc_01", provider="elevenlabs",
        voice_id="v1", model_id="m1", output_format="mp3_44100_128", text=text,
        content_hash="deadbeef", local_path=str(narration_path), alignment=alignment,
        character_count=n, cost_cents=0,
    )

    cues = derive_caption_cues(timeline, [row])
    style = CaptionStyle(resolution=(320, 240), font_family="Noto Sans Devanagari")
    ass_path = work_dir / "captions.ass"
    ass_path.write_text(serialize_ass(cues, style), encoding="utf-8")

    captioned_path = work_dir / "captioned.mp4"
    fragment = subtitles_filter_fragment("0:v", "out", ass_path, FONT_DIR)
    await apply_video_filters(
        silent_path, captioned_path, _RENDER_SETTINGS,
        extra_inputs=[], filter_complex=fragment, output_label="out",
    )

    output_path = tmp_path / f"final_{suffix}.mp4"
    await mux_narration(captioned_path, [narration_path], output_path, _RENDER_SETTINGS)
    return output_path


async def test_captioned_render_is_byte_identical_across_two_independent_runs(tmp_path):
    out_a = await _render_captioned_once(tmp_path, "a")
    out_b = await _render_captioned_once(tmp_path, "b")
    assert _sha256(out_a) == _sha256(out_b)


async def test_captioned_render_has_both_video_and_audio_streams_of_sane_duration(tmp_path):
    output_path = await _render_captioned_once(tmp_path, "smoke")
    video_duration = _stream_duration(output_path, "video")
    audio_duration = _stream_duration(output_path, "audio")
    assert video_duration > 3.5
    assert audio_duration > 3.5
