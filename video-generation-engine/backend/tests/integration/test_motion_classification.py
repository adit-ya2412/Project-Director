"""`app/renderer/motion.py::probe_media` against real files and a real
ffprobe subprocess (A1) - the Pillow-then-ffprobe rule only means
anything if it is checked against genuine media, not fabricated bytes.
"""

from PIL import Image

from app.core.config import settings
from app.renderer.motion import MediaKind, probe_media
from tests.media_fixtures import make_real_clip


def _make_still(path, color=(10, 20, 30)) -> None:
    Image.new("RGB", (64, 64), color=color).save(path, format="PNG")


def _make_animated_gif(path) -> None:
    frames = [Image.new("RGB", (64, 64), color=c) for c in [(255, 0, 0), (0, 255, 0)]]
    frames[0].save(
        path, format="GIF", save_all=True, append_images=frames[1:], duration=100, loop=0
    )


def _make_real_clip(path, duration_s: float = 2.0) -> None:
    """A genuine, short, decodable h264 clip via ffmpeg's own `testsrc`
    source - stands in for a downloaded Kling clip without any network
    call or paid API, same idiom the Ken Burns integration tests already
    use for real still images. Thin wrapper over the shared
    `tests/media_fixtures.py::make_real_clip` (lifted there,
    docs/plans/baked_in_letterbox.md §7, so `tests/unit/assets/
    test_letterbox_crop.py` can build the same kind of fixture)."""
    make_real_clip(path, duration_s=duration_s, width=64, height=64, rate=24)


async def test_a_real_png_classifies_as_still(tmp_path):
    path = tmp_path / "still.png"
    _make_still(path)
    probe = await probe_media(path, ffprobe_binary=settings.ffprobe_binary)
    assert probe.kind is MediaKind.STILL
    assert probe.duration_s is None


async def test_an_animated_gif_still_classifies_as_still(tmp_path):
    """A1's own correction: Pillow OPENS a GIF (even an animated one), so
    this must classify as STILL - `app/renderer/still.py` is what
    flattens it to its first frame, a decision this classifier must not
    make for it by mislabelling it MOTION."""
    path = tmp_path / "animated.gif"
    _make_animated_gif(path)
    probe = await probe_media(path, ffprobe_binary=settings.ffprobe_binary)
    assert probe.kind is MediaKind.STILL
    assert probe.duration_s is None


async def test_a_real_video_clip_classifies_as_motion_with_its_real_duration(tmp_path):
    path = tmp_path / "clip.mp4"
    _make_real_clip(path, duration_s=2.0)
    probe = await probe_media(path, ffprobe_binary=settings.ffprobe_binary)
    assert probe.kind is MediaKind.MOTION
    assert probe.duration_s is not None
    assert abs(probe.duration_s - 2.0) < 0.1


async def test_something_neither_pillow_nor_ffprobe_recognise_falls_back_to_still(tmp_path):
    """Neither signal fires -> STILL, matching `still.py`'s own existing
    fallback ("not something Pillow reads... let the converter take its
    first frame") - a Pillow failure alone must never be read as motion."""
    path = tmp_path / "garbage.bin"
    path.write_bytes(b"not a real media file at all")
    probe = await probe_media(path, ffprobe_binary=settings.ffprobe_binary)
    assert probe.kind is MediaKind.STILL
