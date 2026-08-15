"""Step: select background music (M8, D6/21.2).

## Where this sits, and why (the newly-closed decision)

Runs BEFORE `AwaitApprovalStep`, right after the free search-only
`ResolveAssetsStep` pass - Pixabay search is free, so A5 applies exactly
as it does to visual assets: this is what makes music a supervised
decision at the moment fixing it is still free, rather than a surprise
in the final render. "A human approving a video should hear what it will
sound like" (M8 open decisions, closed 2026-08-15).

## Where the decision lives

The chosen track is recorded in `Timeline.music_plan` via `append_version`
(`produced_by=MUSIC_SELECTION`), never a side table - D6 makes selecting
a track creative, I1 makes the Timeline the only source of truth for a
creative decision, and I2 means only the SELECTION (provider, track id,
source url, licence, attribution, content hash) is recorded there, never
the audio bytes. The audio itself lives at
`storage/{project}/music/{content_hash}.mp3` (D3). `selection_attempted`
is what makes "looked, found nothing suitable" a distinct, resumable
state from "haven't tried yet" - also in the Timeline, per the same
closed decision (no side table for this either).

## Failure is never fatal here (A22's precedent, extended)

A provider raising entirely, every candidate failing its licence gate,
or every fetched candidate failing audio validation all converge on the
same outcome: `selected_track=None`, `selection_attempted=True`. This
step never returns `outcome="failed"` for any of that - a project with
no suitable track must still render, silent-but-narrated, never
unfinished for a reason as minor as "no royalty-free track matched the
mood." This mirrors the pre-approval search pass's own A22 guarantee
(a total search-provider outage does not block the approval gate)
applied to the one remaining pre-approval acquisition question.

## DRY_RUN

`FakeMusicProvider` always finds a canned candidate, so DRY_RUN exercises
this step's real selection logic (search, licence gate, ranking,
recording the choice) end to end - but its "audio" is a literal fake
byte string, not decodable media, same idiom as `FakeNarrationProvider`.
So audio validation (ffprobe) and writing anything to
`storage/.../music/` are both skipped under DRY_RUN; `RenderStep` skips
the music-mux pass for the identical reason it already skips narration
muxing under DRY_RUN - see that step's own docstring.
"""

import hashlib
import uuid as uuid_module

from app.assets.cost import check_budget, total_project_spend_cents
from app.assets.music_ranking import rank_music_candidates
from app.core.config import settings
from app.core.errors import PermanentError
from app.providers.base import MusicProvider, MusicSearchQuery
from app.providers.fakes.music import FakeMusicProvider
from app.providers.pixabay_music import PixabayMusicProvider
from app.renderer.slideshow import probe_duration_seconds
from app.repositories.generated_clip_repository import GeneratedClipRepository
from app.repositories.narration_repository import NarrationRepository
from app.schemas.timeline import MusicTrackSelection, ProducedBy, Timeline
from app.workflow.context import RunContext
from app.workflow.step import StepResult


class SelectMusicStep:
    name = "select_music"
    retryable = True
    max_attempts = 3

    async def is_satisfied(self, ctx: RunContext) -> bool:
        timeline = await ctx.timeline_service.get_active(ctx.project_id)
        if timeline is None or timeline.music_plan is None:
            # No plan to select against - not this step's problem (the
            # Director always sets one in practice; a project that
            # somehow has none has nothing for this step to do).
            return True
        return (
            timeline.music_plan.selected_track is not None
            or timeline.music_plan.selection_attempted
        )

    async def run(self, ctx: RunContext) -> StepResult:
        timeline = await ctx.timeline_service.get_active(ctx.project_id)
        if timeline is None:
            return StepResult(outcome="failed", error="no active timeline to select music for")
        if timeline.music_plan is None:
            return StepResult(outcome="ok")

        selection = await self._select(ctx, timeline)

        def _record(base: Timeline) -> Timeline:
            assert base.music_plan is not None
            base.music_plan.selected_track = selection
            base.music_plan.selection_attempted = True
            return base

        await ctx.timeline_service.append_version(
            ctx.project_id,
            produced_by=ProducedBy.MUSIC_SELECTION,
            transform=_record,
            owns=frozenset({"music_plan"}),
        )
        return StepResult(outcome="ok")

    async def _select(self, ctx: RunContext, timeline: Timeline) -> MusicTrackSelection | None:
        plan = timeline.music_plan
        assert plan is not None
        project_uuid = uuid_module.UUID(ctx.project_id)
        provider: MusicProvider = (
            FakeMusicProvider() if settings.dry_run else PixabayMusicProvider()
        )

        try:
            candidates = await provider.search(
                MusicSearchQuery(
                    mood=plan.mood,
                    tempo=plan.tempo,
                    energy_arc=plan.energy_arc.value,
                    search_terms=plan.search_terms,
                )
            )
        except Exception:  # noqa: BLE001 - A22's precedent: degrade, never block
            return None

        # Licence is a hard gate here too, same principle as visual
        # assets (implementation guide, Phase M6 advice) - a candidate
        # whose licence isn't acceptable is discarded outright.
        eligible = [
            c
            for c in candidates
            if not plan.licence_requirements or c.licence in plan.licence_requirements
        ]
        ranked = rank_music_candidates(eligible, query_terms=plan.search_terms)

        clip_repo = GeneratedClipRepository(ctx.session)
        narration_repo = NarrationRepository(ctx.session)

        for candidate in ranked:
            try:
                already_spent = await total_project_spend_cents(
                    clip_repo=clip_repo, narration_repo=narration_repo, project_id=project_uuid
                )
                check_budget(
                    already_spent_cents=already_spent,
                    additional_cents=settings.music_cost_cents_estimate,
                )
                fetched = await provider.fetch(candidate)
            except Exception:  # noqa: BLE001 - try the next-ranked candidate
                continue

            content_hash = hashlib.sha256(fetched.content).hexdigest()
            if not settings.dry_run:
                # M6 advice, applies equally to audio: "validate what you
                # downloaded" - a download that isn't real, decodable
                # audio must fail HERE, not deep inside ffmpeg during the
                # render. DRY_RUN's fake bytes are deliberately
                # undecodable (see module docstring) and never reach this
                # branch at all.
                path = settings.storage_root / ctx.project_id / "music" / f"{content_hash}.mp3"
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

            return MusicTrackSelection(
                provider=provider.name,
                track_id=candidate.source_id,
                source_url=candidate.source_url,
                licence=candidate.licence,
                attribution=fetched.attribution or candidate.author,
                content_hash=content_hash,
            )

        return None
