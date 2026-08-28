"""`app/renderer/metrics.py` — pure Timeline arithmetic + optional ffmpeg.

No DB. Run from backend/:

    python -m pytest tests/unit/renderer/test_metrics.py --noconftest -q
"""

from __future__ import annotations

import math
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.renderer.captions import MAX_CHARS_PER_CUE, MAX_CUE_DURATION_S
from app.renderer.metrics import (
    _annotate_time_ranges,
    build_render_metrics_report,
    parse_blackdetect,
    parse_ebur128_summary,
    parse_freezedetect,
)
from app.schemas.timeline import (
    Camera,
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
    transition: Transition | None = None,
) -> Shot:
    return Shot(
        id=shot_id,
        order=order,
        intent=ShotIntent.EXPLAIN,
        duration_s=duration_s,
        camera=Camera(movement=movement),
        transition_out=transition or Transition(),
    )


def _timeline(shots: list[Shot], *, scene_id: str = "sc_01") -> Timeline:
    scene = Scene(
        id=scene_id,
        order=0,
        title="Scene",
        duration_s=sum(s.duration_s for s in shots),
        shots=shots,
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


def test_shot_duration_stats_known_list():
    shots = [
        _shot("sh_01", order=0, duration_s=1.0),
        _shot("sh_02", order=1, duration_s=2.0),
        _shot("sh_03", order=2, duration_s=3.0),
        _shot("sh_04", order=3, duration_s=4.0),
    ]
    report = build_render_metrics_report(_timeline(shots))
    stats = report["shots"]
    assert stats["count"] == 4
    d = stats["duration_s"]
    assert d["mean"] == 2.5
    assert d["median"] == 2.5
    assert d["min"] == 1.0
    assert d["max"] == 4.0
    # Sample stddev of 1,2,3,4 = sqrt(5/3) ≈ 1.290994...
    assert d["stddev"] == pytest.approx(math.sqrt(5 / 3))


def test_camera_movement_distribution_shares_sum_to_one():
    shots = [
        _shot("sh_01", order=0, duration_s=1.0, movement=CameraMovement.STATIC),
        _shot("sh_02", order=1, duration_s=1.0, movement=CameraMovement.STATIC),
        _shot("sh_03", order=2, duration_s=1.0, movement=CameraMovement.SLOW_ZOOM),
        _shot("sh_04", order=3, duration_s=1.0, movement=CameraMovement.PUNCH_IN),
    ]
    report = build_render_metrics_report(_timeline(shots))
    counts = report["camera_movements"]["counts"]
    shares = report["camera_movements"]["shares"]
    assert set(counts) == {m.value for m in CameraMovement}
    assert counts["static"] == 2
    assert counts["slow_zoom"] == 1
    assert counts["punch_in"] == 1
    assert counts["pan"] == 0
    assert sum(shares.values()) == pytest.approx(1.0)
    assert shares["static"] == pytest.approx(0.5)


def test_transition_duration_gte_shot_flagged():
    shots = [
        _shot(
            "sh_bad",
            order=0,
            duration_s=0.5,
            transition=Transition(type=TransitionType.DISSOLVE, duration_s=0.8),
        ),
        _shot(
            "sh_ok",
            order=1,
            duration_s=3.0,
            transition=Transition(type=TransitionType.DISSOLVE, duration_s=0.4),
        ),
        _shot(
            "sh_cut",
            order=2,
            duration_s=2.0,
            transition=Transition(type=TransitionType.CUT, duration_s=0.0),
        ),
    ]
    report = build_render_metrics_report(_timeline(shots))
    flagged = report["transitions"]["duration_gte_shot"]
    assert len(flagged) == 1
    assert flagged[0]["shot_id"] == "sh_bad"
    assert flagged[0]["transition_type"] == "dissolve"
    counts = report["transitions"]["counts"]
    assert set(counts) == {t.value for t in TransitionType}
    assert counts["dissolve"] == 2
    assert counts["cut"] == 1
    assert counts["wipeleft"] == 0


def test_transition_duration_gte_incoming_shot_is_flagged():
    shots = [
        _shot(
            "sh_long",
            order=0,
            duration_s=3.0,
            transition=Transition(type=TransitionType.DISSOLVE, duration_s=0.4),
        ),
        _shot("sh_short", order=1, duration_s=0.3),
    ]
    report = build_render_metrics_report(_timeline(shots))
    flagged = report["transitions"]["duration_gte_shot"]
    assert len(flagged) == 1
    assert flagged[0]["shot_id"] == "sh_long"
    assert flagged[0]["compared_shot_id"] == "sh_short"
    assert flagged[0]["compared_duration_s"] == pytest.approx(0.3)


def test_asset_reuse_gap_uses_dissolve_overlap_not_naive_sum():
    # sh_01 (3.0) dissolve 0.4 into sh_02 → sh_02 starts at 2.6 (not 3.0).
    # Same identity on both → min_reuse_gap_s must be 2.6.
    shots = [
        _shot(
            "sh_01",
            order=0,
            duration_s=3.0,
            transition=Transition(type=TransitionType.DISSOLVE, duration_s=0.4),
        ),
        _shot("sh_02", order=1, duration_s=2.0),
        _shot("sh_03", order=2, duration_s=1.0),
    ]
    report = build_render_metrics_report(
        _timeline(shots),
        asset_ids={"sh_01": "asset-a", "sh_02": "asset-a", "sh_03": "asset-b"},
    )
    reuse = report["asset_reuse"]
    assert reuse["available"] is True
    assert reuse["distinct_assets"] == 2
    assert reuse["shot_count"] == 3
    assert reuse["distinct_per_shot"] == pytest.approx(2 / 3)
    assert reuse["min_reuse_gap_s"] == pytest.approx(2.6)


def test_asset_reuse_never_reused_min_gap_null():
    shots = [
        _shot("sh_01", order=0, duration_s=1.0),
        _shot("sh_02", order=1, duration_s=1.0),
    ]
    report = build_render_metrics_report(
        _timeline(shots),
        asset_ids={"sh_01": "a", "sh_02": "b"},
    )
    assert report["asset_reuse"]["min_reuse_gap_s"] is None
    assert report["asset_reuse"]["distinct_per_shot"] == pytest.approx(1.0)


def test_silence_gaps_threshold():
    # Leading 0.6s; 0.2s hole (skip); 1.2s hole (keep). Threshold is 0.5s.
    shots = [_shot("sh_01", order=0, duration_s=3.0)]
    timeline = _timeline(shots)
    alignment = [
        {
            "character_start_times_seconds": [0.6, 1.0, 1.2, 2.4],
            "character_end_times_seconds": [0.9, 1.0, 1.2, 3.0],
        }
    ]
    report = build_render_metrics_report(timeline, alignment_by_scene=alignment)
    gaps = report["silence_gaps"]["gaps"]
    assert gaps is not None
    durations = sorted(g["duration_s"] for g in gaps)
    assert all(abs(d - 0.2) > 1e-9 for d in durations)
    assert any(abs(d - 1.2) < 1e-9 for d in durations)
    assert any(abs(d - 0.6) < 1e-9 for d in durations)


def test_caption_overflow_flags_chars_and_duration():
    cues = [
        {"text": "x" * 80, "start_s": 0.0, "end_s": 1.0},
        {"text": "short", "start_s": 1.0, "end_s": 8.0},
        {"text": "ok cue", "start_s": 8.0, "end_s": 9.0},
    ]
    report = build_render_metrics_report(_timeline([_shot("sh_01", order=0, duration_s=1.0)]), caption_cues=cues)
    flagged = report["caption_overflow"]["cues"]
    assert flagged is not None
    by_index = {c["index"]: c for c in flagged}
    assert set(by_index) == {0, 1}
    assert by_index[0]["reasons"] == ["chars"]
    assert by_index[0]["chars"] == 80
    assert by_index[1]["reasons"] == ["duration"]
    assert by_index[1]["duration_s"] == pytest.approx(7.0)
    assert MAX_CHARS_PER_CUE < 80
    assert MAX_CUE_DURATION_S < 7.0


def test_source_identifies_timeline_and_absent_video():
    report = build_render_metrics_report(_timeline([_shot("sh_01", order=0, duration_s=1.0)]))
    assert report["source"]["timeline_id"] == "t1"
    assert report["source"]["project_id"] == "p1"
    assert report["source"]["version"] == 1
    assert report["source"]["video_path"] is None


def test_defect_ranges_are_annotated_with_overlapping_shots():
    shots = [
        _shot("sh_01", order=0, duration_s=2.0, movement=CameraMovement.STATIC),
        _shot(
            "sh_02",
            order=1,
            duration_s=2.0,
            movement=CameraMovement.PUNCH_IN,
            transition=Transition(type=TransitionType.CUT, duration_s=0.0),
        ),
    ]
    events = [{"start_s": 0.0, "end_s": 2.5, "duration_s": 2.5}]
    annotated = _annotate_time_ranges(events, shots)
    shot_ids = [s["shot_id"] for s in annotated[0]["shots"]]
    assert shot_ids == ["sh_01", "sh_02"]
    movements = {s["shot_id"]: s["camera_movement"] for s in annotated[0]["shots"]}
    assert movements["sh_01"] == "static"
    assert movements["sh_02"] == "punch_in"


def test_missing_optionals_null_with_reasons():
    report = build_render_metrics_report(_timeline([_shot("sh_01", order=0, duration_s=1.0)]))
    assert report["audio"]["mux"] is None
    assert report["audio"]["mux_unavailable_reason"]
    assert report["audio"]["per_scene_narration"] is None
    assert report["audio"]["per_scene_unavailable_reason"]
    assert report["video_defects"]["near_black"] is None
    assert report["video_defects"]["frozen"] is None
    assert report["video_defects"]["unavailable_reason"]
    assert report["silence_gaps"]["gaps"] is None
    assert report["silence_gaps"]["unavailable_reason"]
    assert report["caption_overflow"]["cues"] is None
    assert report["caption_overflow"]["unavailable_reason"]
    assert report["asset_reuse"]["available"] is False
    assert report["asset_reuse"]["unavailable_reason"]


def test_report_does_not_mutate_timeline():
    shots = [_shot("sh_01", order=0, duration_s=2.5)]
    timeline = _timeline(shots)
    before_id = id(timeline)
    before_dur = timeline.scenes[0].shots[0].duration_s
    before_movement = timeline.scenes[0].shots[0].camera.movement
    build_render_metrics_report(timeline, asset_ids={"sh_01": "x"})
    assert id(timeline) == before_id
    assert timeline.scenes[0].shots[0].duration_s == before_dur
    assert timeline.scenes[0].shots[0].camera.movement == before_movement


def test_ebur128_parser_accepts_peak_and_true_peak_labels():
    stderr_peak = """
[Parsed_ebur128_0 @ 0x1] Summary:
  Integrated loudness:
    I:         -14.2 LUFS
    Threshold: -24.2 LUFS
  Loudness range:
    LRA:         5.1 LU
    Threshold: -34.1 LUFS
    LRA low:   -16.0 LUFS
    LRA high:  -10.9 LUFS
  True peak:
    Peak:       -1.2 dBFS
"""
    parsed = parse_ebur128_summary(stderr_peak)
    assert parsed == {
        "integrated_lufs": -14.2,
        "true_peak_db": -1.2,
        "lra": 5.1,
    }

    stderr_true_peak = stderr_peak.replace("Peak:", "True peak:")
    parsed2 = parse_ebur128_summary(stderr_true_peak)
    assert parsed2 is not None
    assert parsed2["true_peak_db"] == pytest.approx(-1.2)


def test_blackdetect_and_freezedetect_parsers():
    black_stderr = (
        "[Parsed_blackdetect_0 @ 0x1] black_start:0 black_end:1.966667 "
        "black_duration:1.966667\n"
    )
    blacks = parse_blackdetect(black_stderr)
    assert len(blacks) == 1
    assert blacks[0]["start_s"] == pytest.approx(0.0)
    assert blacks[0]["duration_s"] == pytest.approx(1.966667)

    freeze_stderr = (
        "[Parsed_freezedetect_0 @ 0x1] lavfi.freezedetect.freeze_start: 0\n"
        "[Parsed_freezedetect_0 @ 0x1] lavfi.freezedetect.freeze_duration: 2.5\n"
        "[Parsed_freezedetect_0 @ 0x1] lavfi.freezedetect.freeze_end: 2.5\n"
    )
    frozen = parse_freezedetect(freeze_stderr)
    assert len(frozen) == 1
    assert frozen[0]["start_s"] == pytest.approx(0.0)
    assert frozen[0]["end_s"] == pytest.approx(2.5)

    open_ended = "[Parsed_freezedetect_0 @ 0x1] lavfi.freezedetect.freeze_start: 0.5\n"
    open_parsed = parse_freezedetect(open_ended, fallback_end_s=3.0)
    assert open_parsed[0]["end_s"] == pytest.approx(3.0)
    assert open_parsed[0]["duration_s"] == pytest.approx(2.5)


def _run_ffmpeg(args: list[str]) -> None:
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(result.stderr[-500:])


@pytest.mark.skipif(_FFMPEG is None, reason="ffmpeg not on PATH")
def test_ffmpeg_mux_loudness_finite(tmp_path: Path):
    video = tmp_path / "tone.mp4"
    _run_ffmpeg(
        [
            _FFMPEG,
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=2:size=320x240:rate=30",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=2",
            "-shortest",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(video),
        ]
    )
    report = build_render_metrics_report(
        _timeline([_shot("sh_01", order=0, duration_s=2.0)]),
        video,
        ffmpeg_binary=_FFMPEG,
    )
    mux = report["audio"]["mux"]
    assert mux is not None, report["audio"]["mux_unavailable_reason"]
    assert math.isfinite(mux["integrated_lufs"])
    assert math.isfinite(mux["true_peak_db"])
    assert math.isfinite(mux["lra"])
    assert report["video_defects"]["unavailable_reason"] is None


@pytest.mark.skipif(_FFMPEG is None, reason="ffmpeg not on PATH")
def test_ffmpeg_near_black_on_black_clip(tmp_path: Path):
    video = tmp_path / "black.mp4"
    _run_ffmpeg(
        [
            _FFMPEG,
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=320x240:r=30:d=2",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-an",
            str(video),
        ]
    )
    report = build_render_metrics_report(
        _timeline([_shot("sh_01", order=0, duration_s=2.0)]),
        video,
        ffmpeg_binary=_FFMPEG,
    )
    assert report["audio"]["mux"] is None
    assert "no audio" in (report["audio"]["mux_unavailable_reason"] or "").lower()
    near_black = report["video_defects"]["near_black"]
    assert near_black is not None
    assert len(near_black) >= 1
    assert near_black[0]["duration_s"] > 0.5
