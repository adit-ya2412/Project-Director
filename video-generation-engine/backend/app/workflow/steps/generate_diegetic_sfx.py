"""Step: generate diegetic SFX clips (long_form_direction.md A8,
2026-09-01).

Runs AFTER `AwaitApprovalStep`, immediately following
`resolve_assets_generate` (`app.workflow.engine.DEFAULT_PIPELINE`) - it
costs real money (ElevenLabs `/v1/sound-generation`), and I6 forbids that
before a human approves, exactly the reasoning that already gates the
generation half of the asset ladder. Unlike the three structural SFX
kinds (`SelectSfxStep`, free search, pre-approval), a diegetic cue is
GENERATED, never searched - `Shot.sfx_cue` is a planner-authored phrase
naming a sound the story wants, and this step turns each distinct
cue-bearing shot into a real clip.

## The cache is mandatory, not an optimisation

ElevenLabs' sound-generation endpoint accepts no seed
(P-LF-A8-GEN-GATE), so I5 for this step comes ENTIRELY from the
prompt-hash cache (`providers/elevenlabs.py::compute_sfx_generation_hash`,
hashing cue + model + duration) - the same shape
`resolve_assets.py::generation_prompt_hash` already uses for images/clips,
reusing `GeneratedClipRepository` as the cache table (its `prompt_hash`
dedup is deliberately GLOBAL, not per-project - see that repository's own
docstring). A cache hit costs nothing and is wired into `check_budget` the
same way image/video generation is (`sfx_diegetic_cost_cents_estimate`).

## Copy-on-reuse (the storage decision, §3 A8)

`GeneratedClipRepository.get_by_prompt_hash` has no project filter, so a
cache hit may point at bytes written by a DIFFERENT project. Unlike the
image/video generation cache (which leaves a live cross-project file
reference - a documented, unresolved finding, see plan §4), this step
follows the RENDER cache's policy instead (`render.py`'s own docstring:
"never a live cross-project file reference"): the audio bytes are always
copied into THIS project's own `sfx/{content_hash}.mp3` before a
`SfxClipSelection` is recorded, regardless of which project the cache row
originated from. `render.py::_sfx_overlays` only ever globs inside the
CURRENT project's own `sfx/` directory, so this copy is what makes a
cross-project reuse resolvable at render time at all, not just an
optimisation.

## Failure isolation (build item 6)

One cue failing must not kill the run. Every per-shot attempt is wrapped;
a failure (transient or permanent) records the shot id in
`SfxPlan.diegetic_failed_shot_ids` (terminal - like a `failed`
ShotBinding, so a resumed run does not retry a cue already known not to
work this run) and processing continues with the rest. That shot simply
renders with no diegetic sound. This step itself always returns
`outcome="ok"`.
"""

from __future__ import annotations

import hashlib
import uuid as uuid_module
from pathlib import Path

from app.assets.cost import budget_cap_cents_for, check_budget, total_project_spend_cents
from app.assets.sfx_levels import measure_peak_dbfs
from app.core.config import settings
from app.core.errors import PermanentError
from app.core.logging import get_logger
from app.providers.base import SoundEffectProvider, SoundEffectRequest
from app.providers.elevenlabs import ElevenLabsSoundEffectProvider, compute_sfx_generation_hash
from app.providers.fakes.sfx_generation import FakeSoundEffectProvider
from app.renderer.audio import measure_integrated_lufs
from app.renderer.slideshow import probe_duration_seconds
from app.repositories.generated_clip_repository import GeneratedClipRepository
from app.repositories.narration_repository import NarrationRepository
from app.schemas.timeline import ProducedBy, SfxClipSelection, SfxKind, SfxPlan, Shot, Timeline
from app.workflow.context import RunContext
from app.workflow.step import StepResult

logger = get_logger(__name__)


def default_sfx_plan_with_no_queries() -> SfxPlan:
    """A bare `SfxPlan` for a project whose Timeline predates the field
    entirely (mirrors `select_sfx.py::default_sfx_plan`, kept as a
    separate, narrower factory here since this step never needs the
    structural-kind `queries`/`licence_requirements` defaults that
    function also sets)."""
    return SfxPlan()


def _cue_bearing_shots(timeline: Timeline) -> list[Shot]:
    return [shot for shot in timeline.all_shots() if (shot.sfx_cue or "").strip()]


def _sfx_provider() -> SoundEffectProvider:
    if settings.dry_run:
        return FakeSoundEffectProvider()
    return ElevenLabsSoundEffectProvider()


class GenerateDiegeticSfxStep:
    name = "generate_diegetic_sfx"
    retryable = True
    max_attempts = 3

    async def is_satisfied(self, ctx: RunContext) -> bool:
        timeline = await ctx.timeline_service.get_active(ctx.project_id)
        if timeline is None:
            return True
        cue_shots = _cue_bearing_shots(timeline)
        if not cue_shots:
            return True
        plan = timeline.sfx_plan
        if plan is None:
            return False
        done = {clip.shot_id for clip in plan.clips if clip.kind == SfxKind.DIEGETIC}
        done |= set(plan.diegetic_failed_shot_ids)
        return all(shot.id in done for shot in cue_shots)

    async def run(self, ctx: RunContext) -> StepResult:
        timeline = await ctx.timeline_service.get_active(ctx.project_id)
        if timeline is None:
            return StepResult(
                outcome="failed", error="no active timeline to generate diegetic sfx for"
            )
        cue_shots = _cue_bearing_shots(timeline)
        if not cue_shots:
            return StepResult(outcome="ok")

        plan = timeline.sfx_plan or default_sfx_plan_with_no_queries()
        already_done = {clip.shot_id for clip in plan.clips if clip.kind == SfxKind.DIEGETIC}
        already_failed = set(plan.diegetic_failed_shot_ids)
        pending = [
            shot
            for shot in cue_shots
            if shot.id not in already_done and shot.id not in already_failed
        ]
        if not pending:
            return StepResult(outcome="ok")

        project_uuid = uuid_module.UUID(ctx.project_id)
        project_dir = settings.storage_root / ctx.project_id
        (project_dir / "sfx").mkdir(parents=True, exist_ok=True)

        clip_repo = GeneratedClipRepository(ctx.session)
        narration_repo = NarrationRepository(ctx.session)
        cap_cents = budget_cap_cents_for(timeline)
        provider = _sfx_provider()

        new_clips: list[SfxClipSelection] = []
        newly_failed: list[str] = []

        for shot in pending:
            cue = (shot.sfx_cue or "").strip()
            # A15 (long_form_direction.md, 2026-09-01): request only as
            # much audio as the shot can ever play - Problem 1 measured
            # every clip generated at a flat `sfx_diegetic_max_clip_s`
            # (8.0s) regardless of the 3.2-5.2s shot it belonged to, so 6
            # of 7 real cues overran their own shot by 2.8-4.8s. Bounding
            # the REQUEST (not just the mux trim) is also cheaper: billing
            # is per second of generated audio (40 credits/s).
            duration_s = min(settings.sfx_diegetic_max_clip_s, shot.duration_s)
            try:
                selection = await self._generate_one(
                    shot=shot,
                    cue=cue,
                    duration_s=duration_s,
                    provider=provider,
                    project_uuid=project_uuid,
                    project_dir=project_dir,
                    clip_repo=clip_repo,
                    narration_repo=narration_repo,
                    cap_cents=cap_cents,
                )
                new_clips.append(selection)
            except Exception as exc:  # noqa: BLE001 - per-shot isolation (Principle 10)
                logger.warning(
                    "generate_diegetic_sfx.shot_failed",
                    extra={"project_id": ctx.project_id, "shot_id": shot.id, "error": str(exc)},
                )
                newly_failed.append(shot.id)

        def _record(base: Timeline) -> Timeline:
            current = base.sfx_plan or default_sfx_plan_with_no_queries()
            current.clips = list(current.clips) + new_clips
            current.diegetic_failed_shot_ids = sorted(
                set(current.diegetic_failed_shot_ids) | set(newly_failed)
            )
            base.sfx_plan = current
            return base

        await ctx.timeline_service.append_version(
            ctx.project_id,
            produced_by=ProducedBy.SFX_SELECTION,
            transform=_record,
            owns=frozenset({"sfx_plan"}),
        )
        return StepResult(outcome="ok")

    async def _generate_one(
        self,
        *,
        shot: Shot,
        cue: str,
        duration_s: float,
        provider: SoundEffectProvider,
        project_uuid: uuid_module.UUID,
        project_dir: Path,
        clip_repo: GeneratedClipRepository,
        narration_repo: NarrationRepository,
        cap_cents: int | None,
    ) -> SfxClipSelection:
        prompt_hash = compute_sfx_generation_hash(
            text=cue, model=settings.sfx_diegetic_model, duration_seconds=duration_s
        )

        cached = await clip_repo.get_by_prompt_hash(prompt_hash)
        cache_hit = (
            cached is not None
            and cached.status == "completed"
            and cached.local_path is not None
            and Path(cached.local_path).exists()
        )
        if cache_hit:
            assert cached is not None and cached.local_path is not None
            # I5/copy-on-reuse (§3 A8's storage decision): a cache hit may
            # belong to a different project's storage (the cache is
            # global, mirroring `generation_prompt_hash`'s own scope).
            # Always copy the bytes into THIS project's own `sfx/`
            # directory below, never reference the other project's path -
            # `render.py::_sfx_overlays` only ever globs the current
            # project's own directory, so this copy is load-bearing, not
            # defensive.
            source_bytes = Path(cached.local_path).read_bytes()
        else:
            already_spent = await total_project_spend_cents(
                clip_repo=clip_repo, narration_repo=narration_repo, project_id=project_uuid
            )
            check_budget(
                already_spent_cents=already_spent,
                additional_cents=settings.sfx_diegetic_cost_cents_estimate,
                cap_cents=cap_cents,
            )
            result = await provider.generate(
                SoundEffectRequest(text=cue, duration_seconds=duration_s)
            )
            source_bytes = result.content

        content_hash = hashlib.sha256(source_bytes).hexdigest()
        dest = project_dir / "sfx" / f"{content_hash}.mp3"
        if not dest.exists():
            dest.write_bytes(source_bytes)

        if not cache_hit:
            # Persist the mandatory prompt-hash cache row now that
            # `dest` (content-hash-named, this project's own copy) is
            # known - this is what makes I5 hold for the NEXT request
            # with this exact cue+model+duration, in this project or any
            # other (the cache is global, mirroring
            # `generation_prompt_hash`).
            await clip_repo.insert(
                project_id=project_uuid,
                shot_id=shot.id,
                provider=provider.name,
                model_id=settings.sfx_diegetic_model,
                prompt=cue,
                prompt_hash=prompt_hash,
                duration_s=duration_s,
                local_path=str(dest),
                cost_cents=settings.sfx_diegetic_cost_cents_estimate,
            )

        peak_dbfs: float | None = None
        measured_duration_s: float | None = None
        loudness_lufs: float | None = None
        if not settings.dry_run:
            peak_dbfs = await measure_peak_dbfs(dest, ffmpeg_binary=settings.ffmpeg_binary)
            # A11 (long_form_direction.md, 2026-09-01): measured ONCE here
            # and persisted below, never re-measured at render time (I5) -
            # same discipline `peak_dbfs` above already follows. Reuses
            # the SAME ebur128 machinery OQ-1a's final-mix loudness pass
            # already depends on (`app/renderer/audio.py::
            # measure_integrated_lufs` -> `app/renderer/ebur128.py`), not
            # a new measurement path.
            loudness_lufs = await measure_integrated_lufs(dest, settings.ffmpeg_binary)
            try:
                measured_duration_s = await probe_duration_seconds(dest, settings.ffprobe_binary)
            except PermanentError:
                measured_duration_s = None

        return SfxClipSelection(
            kind=SfxKind.DIEGETIC,
            provider=provider.name,
            track_id=prompt_hash,
            source_url="",
            licence="generated",
            attribution="",
            content_hash=content_hash,
            shot_id=shot.id,
            peak_dbfs=peak_dbfs,
            duration_s=measured_duration_s,
            loudness_lufs=loudness_lufs,
        )
