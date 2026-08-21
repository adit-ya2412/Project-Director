"""Stillness dual-format: `frame_aspect` is persisted pre-planning."""

import pytest

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
