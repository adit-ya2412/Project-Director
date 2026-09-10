"""`RenderStep` call-site pins — DB-free.

K16.1 finding 1: rebuilding `RenderSettings` in a unit test does not
catch `RenderStep.run` swapping back to `settings.burn_captions`. Spy
the `render_video` call site the way
`test_the_resolved_band_knobs_arrive_in_the_right_parameters` spies
`enforce_emphasis_rules`.
"""

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.schemas.project import ProjectStatus
from app.schemas.timeline import (
    ProducedBy,
    Scene,
    Shot,
    ShotIntent,
    Timeline,
    TimelineStatus,
)
from app.workflow.steps import render as render_mod
from app.workflow.steps.render import RenderStep


def _timeline(*, render_style: str | None) -> Timeline:
    timeline = Timeline(
        timeline_id="t1",
        project_id="00000000-0000-0000-0000-000000000001",
        version=1,
        produced_by=ProducedBy.SHOT_PLANNER,
        status=TimelineStatus.DRAFT,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        scenes=[
            Scene(
                id="sc_01",
                order=0,
                title="t",
                narration_text="hello",
                duration_s=3.0,
                shots=[
                    Shot(
                        id="sh_01",
                        order=0,
                        intent=ShotIntent.EXPLAIN,
                        duration_s=3.0,
                        narration_span=(0, 5),
                    )
                ],
            )
        ],
    )
    timeline.metadata.render_style = render_style
    return timeline


def _ctx(timeline: Timeline) -> SimpleNamespace:
    project = SimpleNamespace(
        video_path=None,
        status=ProjectStatus.AWAITING_REVIEW,
    )

    class _Repo:
        async def get(self, project_id: str):
            return project

        async def update(self, project):
            return project

    class _TimelineService:
        async def get_active(self, project_id: str):
            return timeline

    return SimpleNamespace(
        project_id=timeline.project_id,
        timeline_service=_TimelineService(),
        repo=_Repo(),
        session=None,
        _project=project,
    )


@pytest.mark.asyncio
async def test_render_step_puts_resolved_burn_captions_on_render_video(
    monkeypatch,
):
    """K16.1 finding 1: env OFF + retention_fast → burn_captions True at
    the render_video call site. A revert to settings.burn_captions fails
    this test; rebuilding RenderSettings would not."""
    captured: dict[str, object] = {}

    async def _spy(ctx, timeline, render_settings, **kwargs):
        captured["burn_captions"] = render_settings.burn_captions
        return Path("fake-final.mp4")

    monkeypatch.setattr(settings, "burn_captions", False)
    monkeypatch.setattr(render_mod, "render_video", _spy)

    result = await RenderStep().run(_ctx(_timeline(render_style="retention_fast")))
    assert result.outcome == "ok"
    assert captured["burn_captions"] is True
    assert isinstance(captured["burn_captions"], bool)


@pytest.mark.asyncio
async def test_render_step_burn_captions_falls_through_for_other_styles(
    monkeypatch,
):
    """Unset band → settings.burn_captions. documentary_archival leaves
    the field None, so env OFF reaches render_video as False."""
    captured: dict[str, object] = {}

    async def _spy(ctx, timeline, render_settings, **kwargs):
        captured["burn_captions"] = render_settings.burn_captions
        return Path("fake-final.mp4")

    monkeypatch.setattr(settings, "burn_captions", False)
    monkeypatch.setattr(render_mod, "render_video", _spy)

    result = await RenderStep().run(
        _ctx(_timeline(render_style="documentary_archival"))
    )
    assert result.outcome == "ok"
    assert captured["burn_captions"] is False
    assert isinstance(captured["burn_captions"], bool)


class _StopAfterCollect(RuntimeError):
    """Cheap exit once render_video has called collect."""


@pytest.mark.asyncio
async def test_render_video_passes_resolved_stamp_top_fraction_into_collect(
    monkeypatch, tmp_path
):
    """K16.4 finding 3: resolve lives in render_video, not compositor.

    Spy collect, stub the path up to it, abort after the call. Pins
    retention_fast → 0.18 at the call site.
    """
    from app.renderer.slideshow import RenderSettings

    captured: dict[str, object] = {}

    def _spy_collect(*args, **kwargs):
        captured["stamp_top_fraction"] = kwargs.get("stamp_top_fraction")
        raise _StopAfterCollect("reached collect")

    class _FakeBindingRepo:
        def __init__(self, session):
            pass

        async def list_for_version(self, *args, **kwargs):
            return []

    async def _no_narration(session, timeline):
        return None

    monkeypatch.setattr(settings, "storage_root", tmp_path)
    monkeypatch.setattr(render_mod, "ShotBindingRepository", _FakeBindingRepo)
    monkeypatch.setattr(render_mod, "_resolve_narration_rows", _no_narration)
    monkeypatch.setattr(render_mod, "collect_emphasis_overlay_cues", _spy_collect)

    timeline = _timeline(render_style="retention_fast")
    ctx = _ctx(timeline)
    render_settings = RenderSettings(
        width=720,
        height=1280,
        fps=30,
        pixel_format="yuv420p",
        burn_captions=False,
        watermark_enabled=False,
        burn_text_cards=False,
    )
    with pytest.raises(_StopAfterCollect):
        await render_mod.render_video(
            ctx, timeline, render_settings, output_filename="final.mp4"
        )
    assert captured["stamp_top_fraction"] == 0.18
    assert isinstance(captured["stamp_top_fraction"], float)


@pytest.mark.asyncio
async def test_render_video_passes_none_stamp_top_for_other_styles(
    monkeypatch, tmp_path
):
    """documentary_archival leaves the knob None → collect gets None."""
    from app.renderer.slideshow import RenderSettings

    captured: dict[str, object] = {}

    def _spy_collect(*args, **kwargs):
        captured["stamp_top_fraction"] = kwargs.get("stamp_top_fraction")
        raise _StopAfterCollect("reached collect")

    class _FakeBindingRepo:
        def __init__(self, session):
            pass

        async def list_for_version(self, *args, **kwargs):
            return []

    async def _no_narration(session, timeline):
        return None

    monkeypatch.setattr(settings, "storage_root", tmp_path)
    monkeypatch.setattr(render_mod, "ShotBindingRepository", _FakeBindingRepo)
    monkeypatch.setattr(render_mod, "_resolve_narration_rows", _no_narration)
    monkeypatch.setattr(render_mod, "collect_emphasis_overlay_cues", _spy_collect)

    timeline = _timeline(render_style="documentary_archival")
    ctx = _ctx(timeline)
    render_settings = RenderSettings(
        width=1280,
        height=720,
        fps=30,
        pixel_format="yuv420p",
        burn_captions=False,
        watermark_enabled=False,
        burn_text_cards=False,
    )
    with pytest.raises(_StopAfterCollect):
        await render_mod.render_video(
            ctx, timeline, render_settings, output_filename="final.mp4"
        )
    assert captured["stamp_top_fraction"] is None


# --- K16.8: is_satisfied consults the render fingerprint -----------------


def _ctx_with_video(timeline: Timeline, video_path: Path) -> SimpleNamespace:
    ctx = _ctx(timeline)
    ctx._project.video_path = str(video_path)
    return ctx


class _FakeBinding:
    def __init__(self, updated_at: datetime):
        self.updated_at = updated_at
        self.shot_id = "sh_01"


class _FakeRenderRepo:
    """Returns a canned completed-render row (or None)."""

    def __init__(self, session, *, row):
        self._row = row

    async def get_latest_completed_for_output(self, project_id, *, output_path, is_draft=False):
        assert is_draft is False
        return self._row


def _patch_is_satisfied_deps(
    monkeypatch,
    *,
    current_fingerprint: str,
    stored_fingerprint: str | None,
    bindings: list,
    helper_calls: list | None = None,
):
    """Stub binding list, shared fingerprint helper, and render-row lookup."""

    class _FakeBindingRepo:
        def __init__(self, session):
            pass

        async def list_for_version(self, *args, **kwargs):
            return bindings

    async def _fake_resolve(ctx, timeline, render_settings):
        if helper_calls is not None:
            helper_calls.append("resolve_render_inputs")
        return SimpleNamespace(fingerprint=current_fingerprint)

    stored = (
        None
        if stored_fingerprint is None
        else SimpleNamespace(fingerprint=stored_fingerprint, is_draft=False)
    )

    def _repo_factory(session):
        return _FakeRenderRepo(session, row=stored)

    monkeypatch.setattr(render_mod, "ShotBindingRepository", _FakeBindingRepo)
    monkeypatch.setattr(render_mod, "resolve_render_inputs", _fake_resolve)
    monkeypatch.setattr(render_mod, "RenderRepository", _repo_factory)


@pytest.mark.asyncio
async def test_is_satisfied_false_when_stored_fingerprint_missing(
    monkeypatch, tmp_path
):
    """K16.8 teeth: pre-K16 final.mp4 (no render row / no fingerprint)
    must NOT look done. Today-without-this-slice that situation returned
    True and the 3-second skip shipped the stale file."""
    video = tmp_path / "final.mp4"
    video.write_bytes(b"fake-mp4")
    # Binding older than the file — mtime gate alone would pass.
    old_binding = _FakeBinding(datetime(2020, 1, 1, tzinfo=UTC))
    _patch_is_satisfied_deps(
        monkeypatch,
        current_fingerprint="new",
        stored_fingerprint=None,
        bindings=[old_binding],
    )
    ctx = _ctx_with_video(_timeline(render_style="retention_fast"), video)
    assert await RenderStep().is_satisfied(ctx) is False


@pytest.mark.asyncio
async def test_is_satisfied_false_when_stored_fingerprint_differs(
    monkeypatch, tmp_path
):
    """Stored fingerprint stale vs current inputs → unsatisfied."""
    video = tmp_path / "final.mp4"
    video.write_bytes(b"fake-mp4")
    old_binding = _FakeBinding(datetime(2020, 1, 1, tzinfo=UTC))
    _patch_is_satisfied_deps(
        monkeypatch,
        current_fingerprint="new",
        stored_fingerprint="old",
        bindings=[old_binding],
    )
    ctx = _ctx_with_video(_timeline(render_style="retention_fast"), video)
    assert await RenderStep().is_satisfied(ctx) is False


@pytest.mark.asyncio
async def test_is_satisfied_true_when_fingerprints_match(monkeypatch, tmp_path):
    """Cheap gates pass + stored fingerprint == current → satisfied."""
    video = tmp_path / "final.mp4"
    video.write_bytes(b"fake-mp4")
    old_binding = _FakeBinding(datetime(2020, 1, 1, tzinfo=UTC))
    _patch_is_satisfied_deps(
        monkeypatch,
        current_fingerprint="same-fp",
        stored_fingerprint="same-fp",
        bindings=[old_binding],
    )
    ctx = _ctx_with_video(_timeline(render_style="retention_fast"), video)
    assert await RenderStep().is_satisfied(ctx) is True


@pytest.mark.asyncio
async def test_is_satisfied_binding_mtime_still_wins(monkeypatch, tmp_path):
    """Voice-retry gate: binding newer than video → False even when
    fingerprints would match. Do not break test_narration_voice_retry."""
    video = tmp_path / "final.mp4"
    video.write_bytes(b"fake-mp4")
    # Binding in the future relative to the just-written file.
    future = datetime.now(UTC).replace(year=2099)
    _patch_is_satisfied_deps(
        monkeypatch,
        current_fingerprint="same-fp",
        stored_fingerprint="same-fp",
        bindings=[_FakeBinding(future)],
    )
    ctx = _ctx_with_video(_timeline(render_style="retention_fast"), video)
    assert await RenderStep().is_satisfied(ctx) is False


@pytest.mark.asyncio
async def test_is_satisfied_calls_resolve_render_inputs(monkeypatch, tmp_path):
    """Pin the wiring: is_satisfied must call the shared helper, not
    rebuild the comparison locally (K16.1 unpinned-wiring lesson)."""
    video = tmp_path / "final.mp4"
    video.write_bytes(b"fake-mp4")
    helper_calls: list[str] = []
    _patch_is_satisfied_deps(
        monkeypatch,
        current_fingerprint="fp",
        stored_fingerprint="fp",
        bindings=[],
        helper_calls=helper_calls,
    )
    ctx = _ctx_with_video(_timeline(render_style="retention_fast"), video)
    assert await RenderStep().is_satisfied(ctx) is True
    assert helper_calls == ["resolve_render_inputs"]


@pytest.mark.asyncio
async def test_is_satisfied_and_render_video_share_resolve_render_inputs(
    monkeypatch, tmp_path
):
    """RV2: both call sites invoke the same extracted function identity.
    A swap that rebuilds the comparison only in is_satisfied fails this.
    """
    from app.renderer.slideshow import RenderSettings

    video = tmp_path / "final.mp4"
    video.write_bytes(b"fake-mp4")
    seen: list[object] = []

    async def _tracking_resolve(ctx, timeline, render_settings):
        seen.append(render_mod.resolve_render_inputs)
        return SimpleNamespace(
            fingerprint="shared-fp",
            shot_images={},
            shot_secondary_images={},
            shot_layer_images={},
            shot_focals={},
            narration_paths=None,
            music_segments=None,
            caption_cues=None,
            caption_highlight_size_fraction=None,
            caption_highlight_bold=None,
            caption_highlight_colour=None,
            caption_placements=None,
            alignment_by_scene=None,
            text_card_cues=[],
            overlay_cues=[],
            overlay_palette=None,
            music_gains=SimpleNamespace(bed_gain_db=0.0, duck_gain_db=0.0),
            music_gain_offset_db=0.0,
            music_amix_normalize=0,
            loudness_normalize=False,
            loudness_target_lufs=-14.0,
            loudness_true_peak_db=-1.0,
            narration_level_match=True,
            sfx_whoosh_enabled=True,
            sfx_transition_structural_only=False,
        )

    class _FakeBindingRepo:
        def __init__(self, session):
            pass

        async def list_for_version(self, *args, **kwargs):
            return []

    class _RepoForSatisfied:
        def __init__(self, session):
            pass

        async def get_latest_completed_for_output(self, *args, **kwargs):
            return SimpleNamespace(fingerprint="shared-fp")

        async def get_completed_by_fingerprint(self, fingerprint):
            # Cache hit so render_video returns without encoding.
            return SimpleNamespace(
                output_path=str(video),
                fingerprint=fingerprint,
            )

        async def insert_completed(self, **kwargs):
            return SimpleNamespace(**kwargs)

    async def _fake_probe(path, ffprobe_binary):
        return 1.0

    monkeypatch.setattr(settings, "storage_root", tmp_path)
    monkeypatch.setattr(render_mod, "ShotBindingRepository", _FakeBindingRepo)
    monkeypatch.setattr(render_mod, "resolve_render_inputs", _tracking_resolve)
    monkeypatch.setattr(render_mod, "RenderRepository", _RepoForSatisfied)
    monkeypatch.setattr(render_mod, "probe_duration_seconds", _fake_probe)

    timeline = _timeline(render_style="retention_fast")
    ctx = _ctx_with_video(timeline, video)
    assert await RenderStep().is_satisfied(ctx) is True

    render_settings = RenderSettings(
        width=720,
        height=1280,
        fps=30,
        pixel_format="yuv420p",
        burn_captions=False,
        watermark_enabled=False,
        burn_text_cards=False,
    )
    await render_mod.render_video(
        ctx, timeline, render_settings, output_filename="final.mp4"
    )
    assert len(seen) == 2
    assert seen[0] is seen[1]
    assert seen[0] is render_mod.resolve_render_inputs
