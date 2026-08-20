"""Select SFX clips (parent plan §5.5 / leftover item 2).

Free Openverse search, same licence gate as music, different queries.
Failure never blocks the run — missing clips just skip those events.

⚠ **Position in `DEFAULT_PIPELINE` is load-bearing, and not for the
reason this docstring used to give (§15.6).** It runs before the
approval gate because the search is free, so I6 permits it early — NOT
so a human "hears the whooshes" there: nothing renders SFX until
`RenderStep`, well after approval. The constraint that actually matters
is the other edge: this step must stay BEFORE `NarrationStep`, because
appending a version sets `produced_by=SFX_SELECTION`, and
`render.py::_resolve_narration_rows` returns `None` for any
`produced_by != NARRATION`. Move this step after narration and every
narrated render goes silent, with no error — see the comment above
`DEFAULT_PIPELINE`.
"""

from __future__ import annotations

import hashlib

from app.assets.sfx_ranking import rank_sfx_candidates
from app.core.config import settings
from app.core.errors import PermanentError
from app.providers.base import MusicProvider, MusicSearchQuery
from app.providers.fakes.music import FakeMusicProvider
from app.providers.local_sfx import LocalSfxProvider
from app.providers.openverse_music import OpenverseMusicProvider
from app.renderer.slideshow import probe_duration_seconds
from app.schemas.timeline import ProducedBy, SfxClipSelection, SfxKind, SfxPlan, Timeline
from app.workflow.context import RunContext
from app.workflow.step import StepResult

_DEFAULT_QUERIES: dict[str, list[str]] = {
    SfxKind.WHOOSH.value: ["whoosh", "swoosh cinematic"],
    SfxKind.STINGER.value: ["stinger", "cinematic impact"],
    SfxKind.TRANSITION.value: ["swoosh transition", "whoosh"],
}


def default_sfx_plan() -> SfxPlan:
    return SfxPlan(
        queries=dict(_DEFAULT_QUERIES),
        licence_requirements=["cc0", "by"],
    )


def _sfx_provider() -> MusicProvider:
    if settings.dry_run:
        return FakeMusicProvider()
    if settings.sfx_provider == "openverse":
        return OpenverseMusicProvider()
    return LocalSfxProvider()


class SelectSfxStep:
    name = "select_sfx"
    retryable = True
    max_attempts = 3

    async def is_satisfied(self, ctx: RunContext) -> bool:
        timeline = await ctx.timeline_service.get_active(ctx.project_id)
        if timeline is None:
            return True
        if timeline.sfx_plan is None:
            # Predating this field: do not block render-only.
            return True
        return bool(timeline.sfx_plan.clips) or timeline.sfx_plan.selection_attempted

    async def run(self, ctx: RunContext) -> StepResult:
        timeline = await ctx.timeline_service.get_active(ctx.project_id)
        if timeline is None:
            return StepResult(outcome="failed", error="no active timeline to select sfx for")

        plan = timeline.sfx_plan or default_sfx_plan()
        provider: MusicProvider = _sfx_provider()
        clips: list[SfxClipSelection] = []
        for kind in SfxKind:
            terms = plan.queries.get(kind.value) or _DEFAULT_QUERIES[kind.value]
            selection = await self._select_kind(
                ctx, provider=provider, kind=kind, terms=terms, plan=plan
            )
            if selection is not None:
                clips.append(selection)

        def _record(base: Timeline) -> Timeline:
            current = base.sfx_plan or default_sfx_plan()
            current.clips = clips
            current.selection_attempted = True
            base.sfx_plan = current
            return base

        await ctx.timeline_service.append_version(
            ctx.project_id,
            produced_by=ProducedBy.SFX_SELECTION,
            transform=_record,
            owns=frozenset({"sfx_plan"}),
        )
        return StepResult(outcome="ok")

    async def _select_kind(
        self,
        ctx: RunContext,
        *,
        provider: MusicProvider,
        kind: SfxKind,
        terms: list[str],
        plan: SfxPlan,
    ) -> SfxClipSelection | None:
        try:
            candidates = await provider.search(
                MusicSearchQuery(
                    mood=kind.value,
                    tempo="",
                    energy_arc="flat",
                    search_terms=terms,
                )
            )
        except Exception:  # noqa: BLE001 - one kind missing is not a failed step
            return None

        eligible = [
            c
            for c in candidates
            if not plan.licence_requirements or c.licence in plan.licence_requirements
        ]
        ranked = rank_sfx_candidates(eligible, query_terms=terms)

        for candidate in ranked:
            try:
                fetched = await provider.fetch(candidate)
            except Exception:  # noqa: BLE001
                continue
            content_hash = hashlib.sha256(fetched.content).hexdigest()
            if not settings.dry_run:
                path = settings.storage_root / ctx.project_id / "sfx" / f"{content_hash}.mp3"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(fetched.content)
                try:
                    duration = await probe_duration_seconds(path, settings.ffprobe_binary)
                except PermanentError:
                    path.unlink(missing_ok=True)
                    continue
                if duration <= 0:
                    path.unlink(missing_ok=True)
                    continue
            return SfxClipSelection(
                kind=kind,
                provider=provider.name,
                track_id=candidate.source_id,
                source_url=candidate.source_url,
                licence=candidate.licence,
                attribution=fetched.attribution or candidate.author,
                content_hash=content_hash,
            )
        return None
