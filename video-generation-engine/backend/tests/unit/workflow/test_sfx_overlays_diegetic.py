"""`render.py::_sfx_overlays` - the DIEGETIC per-shot routing
(long_form_direction.md A8). Pure-ish: no ffmpeg, no DB, only real files
on disk (for the same content-hash glob lookup the structural kinds
already use) under a monkeypatched `settings.storage_root`.
"""

from datetime import UTC, datetime

import pytest

from app.assets.sfx_levels import effective_gain_db
from app.core.config import settings
from app.schemas.timeline import (
    ProducedBy,
    Scene,
    SfxClipSelection,
    SfxKind,
    SfxPlan,
    Shot,
    ShotIntent,
    Timeline,
    TimelineStatus,
)
from app.workflow.steps.render import _diegetic_duck_windows, _sfx_overlays

_PROJECT_ID = "proj-1"


def _write_sfx_clip(tmp_path, project_id: str, content_hash: str) -> None:
    sfx_dir = tmp_path / project_id / "sfx"
    sfx_dir.mkdir(parents=True, exist_ok=True)
    (sfx_dir / f"{content_hash}.mp3").write_bytes(b"fake-audio-bytes")


def _timeline(shots: list[Shot], *, clips: list[SfxClipSelection]) -> Timeline:
    scene = Scene(
        id="sc_01",
        order=0,
        title="S",
        duration_s=sum(s.duration_s for s in shots),
        shots=shots,
    )
    return Timeline(
        timeline_id="t1",
        project_id=_PROJECT_ID,
        version=1,
        produced_by=ProducedBy.HUMAN,
        status=TimelineStatus.DRAFT,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        scenes=[scene],
        sfx_plan=SfxPlan(clips=clips),
    )


def _diegetic_clip(
    shot_id: str,
    content_hash: str,
    *,
    peak_dbfs: float | None = None,
    loudness_lufs: float | None = None,
    duration_s: float | None = None,
) -> SfxClipSelection:
    return SfxClipSelection(
        kind=SfxKind.DIEGETIC,
        provider="elevenlabs",
        track_id="prompt-hash",
        source_url="",
        licence="generated",
        content_hash=content_hash,
        shot_id=shot_id,
        peak_dbfs=peak_dbfs,
        loudness_lufs=loudness_lufs,
        duration_s=duration_s,
    )


def test_each_shots_diegetic_event_resolves_to_its_own_clip(tmp_path, monkeypatch):
    """The core correctness risk of a per-shot palette (unlike the
    single-clip-per-kind structural path): shot A's event must never
    play shot B's cue."""
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    monkeypatch.setattr(settings, "dry_run", False)
    _write_sfx_clip(tmp_path, _PROJECT_ID, "hash-a")
    _write_sfx_clip(tmp_path, _PROJECT_ID, "hash-b")

    shot_a = Shot(
        id="sh_01", order=0, intent=ShotIntent.EXPLAIN, duration_s=3.0, sfx_cue="geiger counter"
    )
    shot_b = Shot(
        id="sh_02", order=1, intent=ShotIntent.EXPLAIN, duration_s=4.0, sfx_cue="church bell"
    )
    timeline = _timeline(
        [shot_a, shot_b],
        clips=[_diegetic_clip("sh_01", "hash-a"), _diegetic_clip("sh_02", "hash-b")],
    )

    overlays = _sfx_overlays(timeline, _PROJECT_ID, fps=30, whoosh_enabled=True)

    assert len(overlays) == 2
    by_offset = {round(o.offset_s, 3): o for o in overlays}
    assert by_offset[0.0].path.name == "hash-a.mp3"
    assert by_offset[3.0].path.name == "hash-b.mp3"


def test_diegetic_overlay_carries_the_diegetic_ceiling(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    monkeypatch.setattr(settings, "dry_run", False)
    _write_sfx_clip(tmp_path, _PROJECT_ID, "hash-a")

    shot = Shot(
        id="sh_01", order=0, intent=ShotIntent.EXPLAIN, duration_s=3.0, sfx_cue="geiger counter"
    )
    timeline = _timeline([shot], clips=[_diegetic_clip("sh_01", "hash-a")])

    overlays = _sfx_overlays(timeline, _PROJECT_ID, fps=30, whoosh_enabled=True)

    assert len(overlays) == 1
    assert overlays[0].max_clip_s == settings.sfx_diegetic_max_clip_s


def test_a_shot_with_no_matching_clip_yet_is_silently_skipped(tmp_path, monkeypatch):
    """A cue-bearing shot whose generation hasn't landed yet (or
    permanently failed) must not crash the render - it just gets no
    diegetic overlay, mirroring how a missing structural clip already
    degrades."""
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    monkeypatch.setattr(settings, "dry_run", False)

    shot = Shot(
        id="sh_01", order=0, intent=ShotIntent.EXPLAIN, duration_s=3.0, sfx_cue="geiger counter"
    )
    timeline = _timeline([shot], clips=[])

    overlays = _sfx_overlays(timeline, _PROJECT_ID, fps=30, whoosh_enabled=True)
    assert overlays == []


def test_structural_kind_lookup_is_unaffected_by_diegetic_clips(tmp_path, monkeypatch):
    """`by_kind` must still resolve WHOOSH/STINGER/TRANSITION exactly as
    before - a DIEGETIC clip in the same `clips` list must never leak
    into (or be shadowed by) the structural single-clip-per-kind map."""
    from app.renderer.sfx import SfxEvent

    monkeypatch.setattr(settings, "storage_root", tmp_path)
    monkeypatch.setattr(settings, "dry_run", False)
    _write_sfx_clip(tmp_path, _PROJECT_ID, "hash-whoosh")
    _write_sfx_clip(tmp_path, _PROJECT_ID, "hash-diegetic")

    whoosh_clip = SfxClipSelection(
        kind=SfxKind.WHOOSH,
        provider="local",
        track_id="w",
        source_url="",
        licence="cc0",
        content_hash="hash-whoosh",
    )
    shot = Shot(
        id="sh_01",
        order=0,
        intent=ShotIntent.EXPLAIN,
        duration_s=3.0,
        sfx_cue="geiger counter",
    )
    timeline = _timeline(
        [shot], clips=[whoosh_clip, _diegetic_clip("sh_01", "hash-diegetic")]
    )

    import app.workflow.steps.render as render_module

    monkeypatch.setattr(
        render_module,
        "derive_sfx_events",
        lambda timeline, *, fps, whoosh_enabled: [
            SfxEvent(kind=SfxKind.WHOOSH, offset_s=0.0),
            SfxEvent(kind=SfxKind.DIEGETIC, offset_s=0.0, shot_id="sh_01"),
        ],
    )

    overlays = _sfx_overlays(timeline, _PROJECT_ID, fps=30, whoosh_enabled=True)
    paths = sorted(o.path.name for o in overlays)
    assert paths == ["hash-diegetic.mp3", "hash-whoosh.mp3"]


# -- A11 (long_form_direction.md, 2026-09-01): loudness-based DIEGETIC gain --


def test_diegetic_overlay_uses_loudness_not_peak_when_measured(tmp_path, monkeypatch):
    """The core A11 correctness risk: a DIEGETIC clip with a persisted
    `loudness_lufs` must be gained via that measurement, not via
    `peak_dbfs` - even though `peak_dbfs` is also set (as it always would
    be, since both are measured together in `generate_diegetic_sfx.py`)."""
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    monkeypatch.setattr(settings, "dry_run", False)
    _write_sfx_clip(tmp_path, _PROJECT_ID, "hash-bell")

    shot = Shot(
        id="sh_01", order=0, intent=ShotIntent.EXPLAIN, duration_s=3.0, sfx_cue="church bell"
    )
    clip = _diegetic_clip("sh_01", "hash-bell", peak_dbfs=-0.8, loudness_lufs=-26.1, duration_s=8.0)
    timeline = _timeline([shot], clips=[clip])

    overlays = _sfx_overlays(timeline, _PROJECT_ID, fps=30, whoosh_enabled=True)

    assert len(overlays) == 1
    expected_gain_db = (settings.sfx_diegetic_normalize_target_lufs - -26.1) + (
        settings.sfx_diegetic_gain_db or 0.0
    )
    expected_factor = 10 ** (expected_gain_db / 20)
    assert overlays[0].volume_factor == pytest.approx(expected_factor)
    # And it must NOT equal what the OLD peak-based path would have given -
    # proves the loudness path was actually taken, not a coincidence.
    old_gain_db = effective_gain_db(
        -0.8,
        target_db=settings.sfx_normalize_target_db,
        fallback_db=settings.sfx_gain_db,
        kind_offset_db=settings.sfx_diegetic_gain_db,
    )
    assert overlays[0].volume_factor != pytest.approx(10 ** (old_gain_db / 20))


def test_diegetic_overlay_falls_back_to_peak_when_loudness_unmeasured(tmp_path, monkeypatch):
    """An old timeline / failed probe: `loudness_lufs=None` must reproduce
    the EXACT pre-A11 peak-based volume factor."""
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    monkeypatch.setattr(settings, "dry_run", False)
    _write_sfx_clip(tmp_path, _PROJECT_ID, "hash-bell")

    shot = Shot(
        id="sh_01", order=0, intent=ShotIntent.EXPLAIN, duration_s=3.0, sfx_cue="church bell"
    )
    clip = _diegetic_clip("sh_01", "hash-bell", peak_dbfs=-0.8, loudness_lufs=None, duration_s=8.0)
    timeline = _timeline([shot], clips=[clip])

    overlays = _sfx_overlays(timeline, _PROJECT_ID, fps=30, whoosh_enabled=True)

    expected_gain_db = effective_gain_db(
        -0.8,
        target_db=settings.sfx_normalize_target_db,
        fallback_db=settings.sfx_gain_db,
        kind_offset_db=settings.sfx_diegetic_gain_db,
    )
    assert overlays[0].volume_factor == pytest.approx(10 ** (expected_gain_db / 20))


def test_structural_kinds_gain_is_byte_identical_to_pre_a11(tmp_path, monkeypatch):
    """A11 must not touch WHOOSH/STINGER/TRANSITION at all - same
    `effective_gain_db` call, same result, proven by direct comparison
    rather than by absence of a regression."""
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    monkeypatch.setattr(settings, "dry_run", False)
    _write_sfx_clip(tmp_path, _PROJECT_ID, "hash-whoosh")

    from app.renderer.sfx import SfxEvent

    whoosh_clip = SfxClipSelection(
        kind=SfxKind.WHOOSH,
        provider="local",
        track_id="w",
        source_url="",
        licence="cc0",
        content_hash="hash-whoosh",
        peak_dbfs=-5.0,
    )
    shot = Shot(id="sh_01", order=0, intent=ShotIntent.EXPLAIN, duration_s=3.0)
    timeline = _timeline([shot], clips=[whoosh_clip])

    import app.workflow.steps.render as render_module

    monkeypatch.setattr(
        render_module,
        "derive_sfx_events",
        lambda timeline, *, fps, whoosh_enabled: [SfxEvent(kind=SfxKind.WHOOSH, offset_s=0.0)],
    )

    overlays = _sfx_overlays(timeline, _PROJECT_ID, fps=30, whoosh_enabled=True)

    expected_gain_db = effective_gain_db(
        -5.0,
        target_db=settings.sfx_normalize_target_db,
        fallback_db=settings.sfx_gain_db,
        kind_offset_db=settings.sfx_whoosh_gain_db,
    )
    assert overlays[0].volume_factor == pytest.approx(10 ** (expected_gain_db / 20))


# -- A11: duck windows computed from the Timeline, never the SFX audio ------


def test_diegetic_duck_windows_empty_when_no_cues(tmp_path):
    shot = Shot(id="sh_01", order=0, intent=ShotIntent.EXPLAIN, duration_s=3.0)
    timeline = _timeline([shot], clips=[])
    assert _diegetic_duck_windows(timeline, fps=30, whoosh_enabled=True) == []


def test_diegetic_duck_windows_use_the_persisted_clip_duration():
    shot_a = Shot(
        id="sh_01", order=0, intent=ShotIntent.EXPLAIN, duration_s=3.0, sfx_cue="geiger counter"
    )
    shot_b = Shot(
        id="sh_02", order=1, intent=ShotIntent.EXPLAIN, duration_s=4.0, sfx_cue="church bell"
    )
    timeline = _timeline(
        [shot_a, shot_b],
        clips=[
            _diegetic_clip("sh_01", "hash-a", duration_s=5.0),
            _diegetic_clip("sh_02", "hash-b", duration_s=2.0),
        ],
    )
    windows = _diegetic_duck_windows(timeline, fps=30, whoosh_enabled=True)
    # shot_a starts at 0.0, shot_b starts at 3.0 (compute_shot_start_times)
    assert windows == [(0.0, 5.0), (3.0, 5.0)]


def test_diegetic_duck_window_is_capped_by_the_diegetic_ceiling(monkeypatch):
    """A clip whose measured duration exceeds `sfx_diegetic_max_clip_s`
    must not duck the bed for longer than it will actually play - `mux_sfx`
    trims it to the ceiling (C3d), so the duck window must match."""
    monkeypatch.setattr(settings, "sfx_diegetic_max_clip_s", 2.0)
    shot = Shot(
        id="sh_01", order=0, intent=ShotIntent.EXPLAIN, duration_s=3.0, sfx_cue="machinery hum"
    )
    timeline = _timeline([shot], clips=[_diegetic_clip("sh_01", "hash-a", duration_s=8.0)])
    windows = _diegetic_duck_windows(timeline, fps=30, whoosh_enabled=True)
    assert windows == [(0.0, 2.0)]


def test_diegetic_duck_window_falls_back_to_the_ceiling_when_duration_unmeasured(monkeypatch):
    monkeypatch.setattr(settings, "sfx_diegetic_max_clip_s", 8.0)
    shot = Shot(
        id="sh_01", order=0, intent=ShotIntent.EXPLAIN, duration_s=3.0, sfx_cue="wind"
    )
    timeline = _timeline([shot], clips=[_diegetic_clip("sh_01", "hash-a", duration_s=None)])
    windows = _diegetic_duck_windows(timeline, fps=30, whoosh_enabled=True)
    assert windows == [(0.0, 8.0)]
