"""`app/renderer/video_filters.py::escape_ffmpeg_filter_path` - pure, no
ffmpeg needed. The real filter-string behaviour this escaping makes
possible is proven against a real ffmpeg invocation in
`tests/integration/test_render_captions_determinism.py` and
`tests/integration/test_render_watermark_determinism.py`.
"""

from pathlib import Path

from app.renderer.video_filters import escape_ffmpeg_filter_path


def test_windows_drive_letter_colon_is_escaped():
    escaped = escape_ffmpeg_filter_path(Path("C:/some/path/x.ass"))
    assert escaped.startswith("C\\:")


def test_backslashes_are_normalized_to_forward_slashes():
    escaped = escape_ffmpeg_filter_path(Path("C:/some/path/x.ass"))
    assert "\\" not in escaped.replace("C\\:", "", 1)
