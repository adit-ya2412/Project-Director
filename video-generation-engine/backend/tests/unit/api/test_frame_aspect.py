"""Stillness/illustrated_risograph dual-format: `frame_aspect` is
persisted pre-planning."""

import pytest

from app.api.projects import SetRenderStyleRequest, set_render_style
from app.repositories.project_repository import InMemoryProjectRepository


@pytest.mark.asyncio
async def test_inmemory_create_stores_stillness_reel_aspect():
    repo = InMemoryProjectRepository()
    project = await repo.create("reel", render_style="stillness", frame_aspect="9:16")
    assert project.render_style == "stillness"
    assert project.frame_aspect == "9:16"


@pytest.mark.asyncio
async def test_switching_off_stillness_clears_the_reel_flag():
    repo = InMemoryProjectRepository()
    project = await repo.create("x", render_style="stillness", frame_aspect="9:16")
    project.render_style = "documentary_archival"
    project.frame_aspect = None
    updated = await repo.update(project)
    assert updated.render_style == "documentary_archival"
    assert updated.frame_aspect is None


class _NoActiveTimelineService:
    """Stub matching only the surface `set_render_style` reads
    (`get_active`) - a real `TimelineService` needs a live DB session,
    which this pure-function unit test must not touch."""

    async def get_active(self, project_id: str):
        return None


@pytest.mark.asyncio
async def test_switching_an_existing_project_to_illustrated_risograph_at_16_9_persists_16_9():
    """Regression for the bug flagged in F1's frame_aspect-collapse
    follow-up: `set_render_style` (app/api/projects.py) used to write
    `project.frame_aspect = body.frame_aspect if body.render_style ==
    "stillness" else None` - a literal comparison that agreed with
    `create_project` for `stillness` but silently DISCARDED the override
    for any later style that opted in via `style_accepts_frame_aspect`
    (here, `illustrated_risograph`). Before the fix: this test's `updated.
    frame_aspect` came back `None` even though `frame_aspect_error`
    validated `"16:9"` as legal for this style - a project switched to
    the new style at 16:9 would silently render 9:16 with no error
    anywhere. Now both write paths read through the same resolver."""
    repo = InMemoryProjectRepository()
    project = await repo.create("landscape-risograph")
    updated = await set_render_style(
        project.id,
        SetRenderStyleRequest(render_style="illustrated_risograph", frame_aspect="16:9"),
        repo=repo,
        timeline_service=_NoActiveTimelineService(),
    )
    assert updated.render_style == "illustrated_risograph"
    assert updated.frame_aspect == "16:9"
