"""Real ffmpeg proof that the watermark overlay doesn't break I5, and
that it composes correctly with captions in the SAME re-encode pass
(docs/plans/watermark_implementation_plan.md §1) rather than needing a
second one. Mirrors `test_render_captions_determinism.py`'s own shape.
"""

import hashlib
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image

from app.core.config import settings
from app.renderer.captions import CaptionStyle, FONT_DIR, derive_caption_cues, serialize_ass, subtitles_filter_fragment
from app.renderer.slideshow import RenderSettings, render_timeline
from app.renderer.video_filters import apply_video_filters
from app.renderer.watermark import LOGO_PATH, watermark_filter_fragment
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
    watermark_enabled=True,
)


def _make_image(path: Path, color: tuple[int, int, int]) -> None:
    Image.new("RGB", (320, 240), color).save(path)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _stream_info(path: Path) -> dict:
    import json

    args = [
        settings.ffprobe_binary, "-v", "error", "-print_format", "json",
        "-show_entries", "stream=codec_type,width,height", str(path),
    ]
    return json.loads(subprocess.run(args, capture_output=True, text=True, check=True).stdout)


async def _render_watermarked_once(tmp_path: Path, suffix: str, *, with_captions: bool) -> Path:
    work_dir = tmp_path / f"work_{suffix}"
    work_dir.mkdir()

    image_a = work_dir / "a.png"
    _make_image(image_a, (30, 60, 90))
    shot = Shot(id="sh_01", order=0, intent=ShotIntent.EXPLAIN, duration_s=2.0, narration_span=(0, 20))
    scene = Scene(
        id="sc_01", order=0, title="Scene", duration_s=2.0,
        narration_text="a short caption line", shots=[shot],
    )
    timeline = Timeline(
        timeline_id="t1", project_id="p1", version=1, produced_by=ProducedBy.NARRATION,
        status=TimelineStatus.DRAFT, created_at=datetime(2026, 1, 1, tzinfo=UTC), scenes=[scene],
    )

    silent_path = work_dir / "silent.mp4"
    await render_timeline(timeline, {"sh_01": image_a}, _RENDER_SETTINGS, silent_path, work_dir=work_dir)

    fragments: list[str] = []
    extra_inputs: list[Path] = []
    current_label = "0:v"

    if with_captions:
        n = len(scene.narration_text)
        alignment = {
            "characters": list(scene.narration_text),
            "character_start_times_seconds": [i * 2.0 / n for i in range(n)],
            "character_end_times_seconds": [(i + 1) * 2.0 / n for i in range(n)],
        }
        row = NarrationModel(
            id=uuid.uuid4(), project_id=uuid.uuid4(), scene_id="sc_01", provider="elevenlabs",
            voice_id="v1", model_id="m1", output_format="mp3_44100_128", text=scene.narration_text,
            content_hash="deadbeef", local_path="/fake.mp3", alignment=alignment,
            character_count=n, cost_cents=0,
        )
        cues = derive_caption_cues(timeline, [row])
        style = CaptionStyle(resolution=(320, 240), font_family="Noto Sans Devanagari")
        ass_path = work_dir / "captions.ass"
        ass_path.write_text(serialize_ass(cues, style), encoding="utf-8")
        fragments.append(subtitles_filter_fragment(current_label, "captioned", ass_path, FONT_DIR))
        current_label = "captioned"

    extra_inputs.append(LOGO_PATH)
    fragments.append(
        watermark_filter_fragment(
            current_label, "out", len(extra_inputs),
            frame_width=320, position="top_right",
            width_fraction=0.10, margin_fraction=0.03, opacity=0.65,
        )
    )
    current_label = "out"

    output_path = tmp_path / f"final_{suffix}.mp4"
    await apply_video_filters(
        silent_path, output_path, _RENDER_SETTINGS,
        extra_inputs=extra_inputs, filter_complex=";".join(fragments), output_label=current_label,
    )
    return output_path


async def test_watermarked_render_is_byte_identical_across_two_independent_runs(tmp_path):
    out_a = await _render_watermarked_once(tmp_path, "a", with_captions=False)
    out_b = await _render_watermarked_once(tmp_path, "b", with_captions=False)
    assert _sha256(out_a) == _sha256(out_b)


async def test_watermark_and_captions_compose_in_one_pass_and_stay_deterministic(tmp_path):
    out_a = await _render_watermarked_once(tmp_path, "a", with_captions=True)
    out_b = await _render_watermarked_once(tmp_path, "b", with_captions=True)
    assert _sha256(out_a) == _sha256(out_b)

    info = _stream_info(out_a)
    video_streams = [s for s in info["streams"] if s["codec_type"] == "video"]
    assert len(video_streams) == 1
    assert video_streams[0]["width"] == 320
    assert video_streams[0]["height"] == 240
