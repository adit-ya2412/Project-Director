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
