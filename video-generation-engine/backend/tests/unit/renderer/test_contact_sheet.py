"""`app/renderer/contact_sheet.py` — midpoints + optional ffmpeg sheet.

No DB. Run from backend/:

    python -m pytest tests/unit/renderer/test_contact_sheet.py --noconftest -q
"""

from __future__ import annotations

import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.renderer.contact_sheet import (
    _duration_gte_shot_ids,
    _shot_midpoints,
    build_contact_sheet,
)
from app.schemas.timeline import (
    Camera,
    CameraDirection,
    CameraMovement,
    ProducedBy,
    Scene,
    Shot,
    ShotIntent,
    Timeline,
    TimelineStatus,
    Transition,
    TransitionType,
)

_FFMPEG = shutil.which("ffmpeg")


def _shot(
    shot_id: str,
    *,
    order: int,
    duration_s: float,
    movement: CameraMovement = CameraMovement.STATIC,
    direction: CameraDirection = CameraDirection.NONE,
    intensity: float = 0.15,
    transition: Transition | None = None,
    narration_span: tuple[int, int] | None = None,
) -> Shot:
    return Shot(
        id=shot_id,
        order=order,
        intent=ShotIntent.EXPLAIN,
        duration_s=duration_s,
        camera=Camera(movement=movement, direction=direction, intensity=intensity),
        transition_out=transition or Transition(),
        narration_span=narration_span,
    )


def _timeline(
    shots: list[Shot],
    *,
    scene_id: str = "sc_01",
    narration_text: str = "",
) -> Timeline:
    scene = Scene(
        id=scene_id,
        order=0,
        title="Scene",
        duration_s=sum(s.duration_s for s in shots),
        shots=shots,
        narration_text=narration_text,
    )
    return Timeline(
        timeline_id="t1",
        project_id="p1",
        version=1,
        produced_by=ProducedBy.HUMAN,
        status=TimelineStatus.DRAFT,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        scenes=[scene],
    )


def test_shot_midpoints_dissolve_not_naive_sum():
    # sh_01 (3.0) dissolve 0.4 into sh_02 (2.0):
    # starts: sh_01=0.0, sh_02=2.6 (not 3.0)
    # midpoints: 1.5 and 2.6 + 1.0 = 3.6
    shots = [
        _shot(
            "sh_01",
            order=0,
            duration_s=3.0,
            transition=Transition(type=TransitionType.DISSOLVE, duration_s=0.4),
        ),
        _shot("sh_02", order=1, duration_s=2.0),
    ]
    mids = _shot_midpoints(_timeline(shots))
    assert mids["sh_01"] == pytest.approx(1.5)
    assert mids["sh_02"] == pytest.approx(3.6)
    # Naive sum of durations would put sh_02 midpoint at 3.0 + 1.0 = 4.0.
    assert mids["sh_02"] != pytest.approx(4.0)


def test_duration_gte_shot_flags_outgoing_hazard():
    shots = [
        _shot(
            "sh_bad",
            order=0,
            duration_s=0.5,
            transition=Transition(type=TransitionType.DISSOLVE, duration_s=0.8),
        ),
        _shot("sh_ok", order=1, duration_s=3.0),
    ]
    assert _duration_gte_shot_ids(shots) == {"sh_bad"}


def test_duration_gte_shot_flags_incoming_shorter():
    shots = [
        _shot(
            "sh_long",
            order=0,
            duration_s=3.0,
            transition=Transition(type=TransitionType.DISSOLVE, duration_s=0.4),
        ),
        _shot("sh_short", order=1, duration_s=0.3),
    ]
    assert _duration_gte_shot_ids(shots) == {"sh_long"}


def _run_ffmpeg(args: list[str]) -> None:
    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr[-500:])


@pytest.mark.skipif(_FFMPEG is None, reason="ffmpeg not on PATH")
def test_build_contact_sheet_two_shots(tmp_path: Path):
    video = tmp_path / "clip.mp4"
    _run_ffmpeg(
        [
            _FFMPEG,
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=4:size=320x240:rate=30",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-an",
            str(video),
        ]
    )
    narration = "Hello world from shot one then shot two continues here."
    shots = [
        _shot(
            "sh_01",
            order=0,
            duration_s=2.0,
            movement=CameraMovement.SLOW_ZOOM,
            direction=CameraDirection.IN,
            intensity=0.4,
            transition=Transition(type=TransitionType.CUT, duration_s=0.0),
            narration_span=(0, 28),
        ),
        _shot(
            "sh_02",
            order=1,
            duration_s=2.0,
            movement=CameraMovement.PAN,
            direction=CameraDirection.LEFT,
            narration_span=(28, len(narration)),
        ),
    ]
    timeline = _timeline(shots, narration_text=narration)
    out_html = tmp_path / "clip.contact.html"
    written = build_contact_sheet(
        timeline,
        video,
        out_html,
        asset_ids={"sh_01": "hash_a", "sh_02": "hash_a"},
        ffmpeg_binary=_FFMPEG,
    )
    assert written == out_html
    assert out_html.is_file()
    text = out_html.read_text(encoding="utf-8")
    assert "sh_01" in text
    assert "sh_02" in text
    assert "<img" in text
    assert 'class="cell cell-flagged"' not in text  # cut + healthy durations
    assert "reused: yes" in text
    thumbs = tmp_path / "clip.contact"
    assert (thumbs / "sh_01.jpg").is_file()
    assert (thumbs / "sh_02.jpg").is_file()
