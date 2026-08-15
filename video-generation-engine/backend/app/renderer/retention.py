"""Draft retention (D3, M8 step 6): `settings.draft_retention_days` wired
to an actual purge, not just a config value nothing reads.

## Why this lives here and not in a scheduler

No scheduler/cron infrastructure exists anywhere in this codebase yet
(no Celery beat, no APScheduler, nothing) - adding one JUST for this
would be new infrastructure for a single call site, the opposite of
"no new dependencies". Instead, `purge_expired_drafts` is invoked
OPPORTUNISTICALLY from the one place a draft render already happens
(`POST /projects/{id}/render/draft`, `app/api/projects.py`) - every
draft request is also a chance to sweep whatever has aged out since the
last one. This means retention is only as prompt as draft traffic
itself (an project that never requests another draft never triggers a
sweep of its own old one) - acceptable for a low-stakes disk-space
cleanup, not acceptable if this were, say, a security/compliance
deletion requirement. If real background scheduling is ever added for
other reasons, this same function is the obvious thing to hang off it -
nothing about it assumes it's called from a request handler.

## Why deleting the file is always safe, never a silent-corruption risk

`render_video`'s cache-hit check (`app/workflow/steps/render.py`) already
verifies `Path(cached.output_path).exists()` before trusting a
fingerprint match - a purged draft whose `render` ROW briefly outlived
its file (a purge mid-request, in theory) would simply be treated as a
cache MISS and re-rendered for real, never as a hit against a missing
file. This function deletes the row in the same pass specifically to
avoid leaving that stale-row window open any longer than it has to, but
the correctness of the cache does not depend on it doing so.

## Identifying "a draft" without a dedicated column

There is no `is_draft` flag on `render` - the same width/height pair
(`settings.draft_width`/`draft_height`) that keeps a draft and a final
render from ever colliding on one fingerprint (see
`app/renderer/fingerprint.py`) is reused here to identify which
completed rows this sweep is even allowed to touch. A final render at
`settings.render_width`/`render_height` is never a candidate, no matter
its age - only D3's own "draft" retention window applies to it.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.repositories.render_repository import RenderRepository

logger = get_logger(__name__)


async def purge_expired_drafts(session: AsyncSession, *, now: datetime | None = None) -> int:
    """Deletes every completed draft-dimension `render` row (and its file
    on disk, if still present) older than `settings.draft_retention_days`.
    Returns the number of rows purged - callers that care (tests, mainly)
    can assert on it; the draft endpoint itself just fires this and moves
    on."""
    cutoff = (now or datetime.now(UTC)) - timedelta(days=settings.draft_retention_days)
    repo = RenderRepository(session)
    expired = await repo.list_completed_drafts_older_than(
        cutoff, width=settings.draft_width, height=settings.draft_height
    )
    for row in expired:
        if row.output_path:
            path_obj = Path(row.output_path)
            if path_obj.exists():
                path_obj.unlink()
        await repo.delete(row)
    if expired:
        logger.info(
            "render.drafts_purged",
            extra={"count": len(expired), "retention_days": settings.draft_retention_days},
        )
    return len(expired)
