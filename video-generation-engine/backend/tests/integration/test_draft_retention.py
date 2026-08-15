"""D3/M8 step 6: `settings.draft_retention_days` actually wired to a real
purge (`app/renderer/retention.py`), not left as a config value nothing
reads. Exercises `purge_expired_drafts` directly against the real DB -
three rows (expired draft, fresh draft, expired FINAL) prove it purges
exactly the one row it should: draft-dimensioned AND past the retention
window, never a final render regardless of age, never a draft still
within the window.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest_asyncio

from app.core.config import settings
from app.db.session import async_session_factory
from app.renderer.retention import purge_expired_drafts
from app.repositories.project_repository import PostgresProjectRepository
from app.repositories.render_repository import RenderRepository


@pytest_asyncio.fixture
async def project_id() -> str:
    async with async_session_factory() as session:
        project = await PostgresProjectRepository(session).create("draft-retention-test")
        return project.id


async def _insert_render_row(
    session,
    project_id: str,
    *,
    width: int,
    height: int,
    created_at: datetime,
    fingerprint: str,
) -> tuple[str, object]:
    import uuid as uuid_module

    output_dir = settings.storage_root / project_id / "renders"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{fingerprint}.mp4"
    output_path.write_bytes(b"not real video bytes, just needs to exist on disk")

    row = await RenderRepository(session).insert_completed(
        project_id=uuid_module.UUID(project_id),
        output_path=str(output_path),
        fingerprint=fingerprint,
        settings={"width": width, "height": height, "fps": 30, "pixel_format": "yuv420p"},
        width=width,
        height=height,
        fps=30,
        duration_s=1.0,
    )
    # `insert_completed` always stamps `created_at` via the column's own
    # `server_default=func.now()` - overridden here directly so the test
    # can simulate "created N days ago" without waiting N real days.
    row.created_at = created_at
    await session.flush()
    return str(output_path), row


async def test_purge_removes_only_expired_draft_dimensioned_rows(project_id):
    now = datetime.now(UTC)
    long_ago = now - timedelta(days=settings.draft_retention_days + 1)
    recently = now - timedelta(days=1)

    async with async_session_factory() as session:
        expired_draft_path, _ = await _insert_render_row(
            session,
            project_id,
            width=settings.draft_width,
            height=settings.draft_height,
            created_at=long_ago,
            fingerprint="fp-expired-draft",
        )
        fresh_draft_path, _ = await _insert_render_row(
            session,
            project_id,
            width=settings.draft_width,
            height=settings.draft_height,
            created_at=recently,
            fingerprint="fp-fresh-draft",
        )
        expired_final_path, _ = await _insert_render_row(
            session,
            project_id,
            width=settings.render_width,
            height=settings.render_height,
            created_at=long_ago,
            fingerprint="fp-expired-final",
        )
        await session.commit()

    async with async_session_factory() as session:
        purged_count = await purge_expired_drafts(session, now=now)
        await session.commit()

    assert purged_count == 1

    assert not Path(expired_draft_path).exists()  # file removed
    assert Path(fresh_draft_path).exists()  # untouched: not expired yet
    assert Path(expired_final_path).exists()  # untouched: final, not a draft, regardless of age

    async with async_session_factory() as session:
        render_repo = RenderRepository(session)
        assert await render_repo.get_completed_by_fingerprint("fp-expired-draft") is None
        assert await render_repo.get_completed_by_fingerprint("fp-fresh-draft") is not None
        assert await render_repo.get_completed_by_fingerprint("fp-expired-final") is not None


async def test_purge_is_a_no_op_when_nothing_has_expired(project_id):
    now = datetime.now(UTC)
    recently = now - timedelta(hours=1)

    async with async_session_factory() as session:
        await _insert_render_row(
            session,
            project_id,
            width=settings.draft_width,
            height=settings.draft_height,
            created_at=recently,
            fingerprint="fp-fresh-only",
        )
        await session.commit()

    async with async_session_factory() as session:
        purged_count = await purge_expired_drafts(session, now=now)
        await session.commit()

    assert purged_count == 0
