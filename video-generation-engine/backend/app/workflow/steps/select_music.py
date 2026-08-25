"""Step: select background music (M8, D6/21.2).

## Where this sits, and why (the newly-closed decision)

Runs BEFORE `AwaitApprovalStep`, right after the free search-only
`ResolveAssetsStep` pass - the real music search (Openverse) is free, so
A5 applies exactly as it does to visual assets: this is what makes music
a supervised decision at the moment fixing it is still free, rather than
a surprise in the final render. "A human approving a video should hear
what it will sound like" (M8 open decisions, closed 2026-08-15).

## Which provider (`settings.music_provider`)

`_PROVIDERS` maps the config string to a real class. Default is
`"openverse"` (`app/providers/openverse_music.py`) - free, keyless, and
verified live to actually work, unlike `"pixabay"`
(`app/providers/pixabay_music.py`), kept only as honest, non-functional
scaffolding for whenever a real Pixabay Music API might exist.

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

A provider raising entirely, ranking returning nothing, or every fetched
candidate failing audio validation all converge on the same outcome:
`selected_track=None`, `selection_attempted=True`. This
step never returns `outcome="failed"` for any of that - a project with
no suitable track must still render, silent-but-narrated, never
unfinished for a reason as minor as "no royalty-free track matched the
mood." This mirrors the pre-approval search pass's own A22 guarantee
(a total search-provider outage does not block the approval gate)
applied to the one remaining pre-approval acquisition question.

## DRY_RUN

`FakeMusicProvider` always finds a canned candidate, so DRY_RUN exercises
this step's real selection logic (search, ranking, recording the
choice - no licence gate, per this step's own 2026-08-25 decision to
stop filtering music by licence) end to end - but its "audio" is a literal fake
byte string, not decodable media, same idiom as `FakeNarrationProvider`.
So audio validation (ffprobe) and writing anything to
`storage/.../music/` are both skipped under DRY_RUN; `RenderStep` skips
the music-mux pass for the identical reason it already skips narration
muxing under DRY_RUN - see that step's own docstring.
"""

import hashlib
import uuid as uuid_module
from collections.abc import Callable

from app.assets.cost import budget_cap_cents_for, check_budget, total_project_spend_cents
from app.assets.music_ranking import pick_seeded_top, rank_music_candidates
from app.core.config import settings
from app.core.errors import PermanentError
from app.providers.base import MusicProvider, MusicSearchQuery
from app.providers.fakes.music import FakeMusicProvider
from app.providers.local_music import LocalMusicProvider
from app.providers.openverse_music import OpenverseMusicProvider
from app.providers.pixabay_music import PixabayMusicProvider
from app.renderer.slideshow import probe_duration_seconds
from app.repositories.generated_clip_repository import GeneratedClipRepository
from app.repositories.narration_repository import NarrationRepository
from app.schemas.timeline import ActMusicBed, MusicTrackSelection, ProducedBy, Scene, Timeline
from app.timeline.acts import group_scenes_by_act, uses_per_act_beds
from app.workflow.context import RunContext
from app.workflow.step import StepResult

# `settings.music_provider` selects the implementation (M8, 21.1) -
# "local" (the curated library, §11 step 6) is the real, working default
# now; "openverse" stays available and working, kept for whenever a
# project needs something outside the curated library's 54 tracks;
# "pixabay" is kept only as honest, non-functional scaffolding (see that
# module's own docstring). An unrecognised value falls back to "local"
# rather than raising - a typo in config should degrade to "still tries
# to find music", not crash the whole pipeline.
_PROVIDERS: dict[str, Callable[[], MusicProvider]] = {
    "local": LocalMusicProvider,
    "openverse": OpenverseMusicProvider,
    "pixabay": PixabayMusicProvider,
}


def _mean_shot_duration_s(scenes: list[Scene]) -> float:
    """Plan §5.3: tempo-fit ranks against measured (here: planned) mean
    shot length. Empty shot list → 0, which disables the tempo key."""
    shots = [shot for scene in scenes for shot in scene.shots]
    if not shots:
        return 0.0
    return sum(shot.duration_s for shot in shots) / len(shots)


def _real_music_provider() -> MusicProvider:
    provider_cls = _PROVIDERS.get(settings.music_provider, LocalMusicProvider)
    return provider_cls()


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

        if uses_per_act_beds(timeline):
            beds: list[ActMusicBed] = []
            previous_track_id: str | None = None
            for act_id, scenes in group_scenes_by_act(timeline.scenes):
                act_duration_s = sum(scene.duration_s for scene in scenes) or (
                    timeline.metadata.total_duration_s
                )
                exclude = {previous_track_id} if previous_track_id else set()
                selection = await self._select(
                    ctx,
                    timeline,
                    video_duration_s=act_duration_s,
                    mean_shot_duration_s=_mean_shot_duration_s(scenes),
                    exclude_source_ids=exclude,
                )
                beds.append(ActMusicBed(act_id=act_id, selected_track=selection))
                if selection is not None:
                    previous_track_id = selection.track_id

            def _record_acts(base: Timeline) -> Timeline:
                assert base.music_plan is not None
                base.music_plan.act_beds = beds
                # First bed also fills `selected_track` so Path A readers
                # (retry UI, cost estimate) still see a selection.
                base.music_plan.selected_track = beds[0].selected_track if beds else None
                base.music_plan.selection_attempted = True
                return base

            record = _record_acts
        else:
            selection = await self._select(
                ctx,
                timeline,
                video_duration_s=timeline.metadata.total_duration_s,
                mean_shot_duration_s=_mean_shot_duration_s(timeline.scenes),
            )

            def _record_one(base: Timeline) -> Timeline:
                assert base.music_plan is not None
                base.music_plan.selected_track = selection
                base.music_plan.act_beds = []
                base.music_plan.selection_attempted = True
                return base

            record = _record_one

        await ctx.timeline_service.append_version(
            ctx.project_id,
            produced_by=ProducedBy.MUSIC_SELECTION,
            transform=record,
            owns=frozenset({"music_plan"}),
        )
        return StepResult(outcome="ok")

    async def _select(
        self,
        ctx: RunContext,
        timeline: Timeline,
        *,
        video_duration_s: float,
        mean_shot_duration_s: float = 0.0,
        exclude_source_ids: set[str] | frozenset[str] = frozenset(),
    ) -> MusicTrackSelection | None:
        plan = timeline.music_plan
        assert plan is not None
        project_uuid = uuid_module.UUID(ctx.project_id)
        provider: MusicProvider = (
            FakeMusicProvider() if settings.dry_run else _real_music_provider()
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

        # Licence gate removed for music (2026-08-25, explicit product
        # decision - unlike the visual asset ladder, which still gates on
        # licence). It was also silently broken: the Director's prompt
        # emits `licence_requirements` in Openverse's short vocabulary
        # ("cc0"/"by"), but the curated local library - the default
        # provider - reports full Creative Commons strings ("cc-by-4.0",
        # "cc0-1.0", ...), so the exact-match gate rejected every track
        # in the library, every time, regardless of this decision.
        eligible = candidates
        ranked = rank_music_candidates(
            eligible,
            query_terms=plan.search_terms,
            # Best current estimate of the finished video's length - the
            # planner's own duration arithmetic, not yet narration-
            # corrected at this point in the pipeline (SelectMusicStep
            # runs before narration reconciliation). Good enough for a
            # duration FLOOR (see music_ranking.py) - it only needs to be
            # in the right ballpark, not exact. Per-act calls pass that
            # act's duration so a 90 s act does not inherit a 10 min floor.
            video_duration_s=video_duration_s,
            mean_shot_duration_s=mean_shot_duration_s,
        )
        # C7: consecutive acts must not share a bed when any other
        # candidate exists. Repeating a bed from act 1 at act 4 is fine.
        # The full library is the pool (mood×energy is 3 tracks/cell), so
        # excluding the previous id is what "move across the energy axis
        # within one mood" actually is — ranking already sees mood/energy
        # in tags; we do not pre-filter energy and then get stuck.
        preferred = [c for c in ranked if c.source_id not in exclude_source_ids]
        ranked = preferred or ranked

        # M10 / analysis.md C2.2: break near-ties by a PROJECT-seeded hash,
        # not plain source_id - two projects with the same brief must not
        # land on the same track ("Documentary Music Strings" owned every
        # documentary brief before this). Quality still decides outside
        # the near-tie band; see pick_seeded_top's own docstring.
        if not ranked:
            return None
        chosen = pick_seeded_top(
            ranked,
            query_terms=plan.search_terms,
            video_duration_s=video_duration_s,
            mean_shot_duration_s=mean_shot_duration_s,
            seed=ctx.project_id,
        )
        ordered = [chosen] + [c for c in ranked if c.source_id != chosen.source_id]

        clip_repo = GeneratedClipRepository(ctx.session)
        narration_repo = NarrationRepository(ctx.session)
        cap_cents = budget_cap_cents_for(timeline)

        for candidate in ordered:
            try:
                already_spent = await total_project_spend_cents(
                    clip_repo=clip_repo, narration_repo=narration_repo, project_id=project_uuid
                )
                check_budget(
                    already_spent_cents=already_spent,
                    additional_cents=settings.music_cost_cents_estimate,
                    cap_cents=cap_cents,
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
