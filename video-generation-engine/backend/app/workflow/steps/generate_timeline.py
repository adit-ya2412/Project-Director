"""Step 1: script -> Timeline.

DRY_RUN=true (default): `FakeTimelinePlanner` fills the whole Timeline in
one shot via one `append_version` call - unchanged since M4, so the
walking skeleton keeps working with zero API keys.

DRY_RUN=false (M5): the real Director -> Scene Planner -> Shot Planner ->
Asset Planner chain runs, each stage its own `append_version` call with
its own `owns` set. Each stage is individually resumable via the active
Timeline's own state (no separate progress flag) - a crash after the
Scene Planner but before the Shot Planner resumes by re-checking what the
Timeline already has, exactly like the workflow engine's step-level
resumability (M4), one level deeper.
"""

from app.core.config import settings
from app.core.errors import TransientError
from app.planners.asset.planner import AssetPlanner
from app.planners.director.planner import DirectorPlanner
from app.planners.fragments import split_narration_fragments
from app.planners.scene.planner import ScenePlanner
from app.planners.shot.planner import ShotPlanner
from app.providers.fakes.llm import FakeTimelinePlanner
from app.providers.openai_provider import OpenAIPlanningProvider
from app.repositories.llm_call_repository import LlmCallRepository
from app.schemas.timeline import ProducedBy, Timeline
from app.script.styles import ConstraintBundle, resolve_constraint_bundle
from app.timeline.duration import compute_timeline_duration
from app.workflow.context import RunContext
from app.workflow.step import StepResult
from app.workflow.steps.select_sfx import default_sfx_plan

_FAKE_PLANNER_OWNS = frozenset(
    {"metadata", "creative_context", "music_plan", "sfx_plan", "scenes"}
)


def _validate_against_style(timeline: Timeline) -> list[str]:
    """The ONE place this file resolves a style's bounds for validation
    purposes - used by BOTH `_is_fully_planned` (the resume/idempotency
    check) and `run()`'s own post-planning gate. Extracted as a single
    shared function (R1 fix, motion_new_styles_and_long_form_videos.md
    §13.1, 2026-08-18) after these two calls existed separately and
    quietly disagreed: `run()` used to read the flat `settings.*` bounds
    directly while this function already resolved style-derived ones via
    `resolve_constraint_bundle` - so for `retention_fast`, the Shot
    Planner was authorised (via this same function, through
    `_is_fully_planned`'s reasoning) to emit shots as short as 0.8s or up
    to 58 of them, and `run()`'s OWN separate flat-settings check
    rejected exactly that timeline every time - a loud failure after the
    Director, Scene Planner, and every Shot Planner call had already been
    paid for. Two validators of one invariant must not be able to
    diverge; a single function neither call site can bypass is what
    makes that true, not just making both agree today.

    `resolve_constraint_bundle` (Track B, 2026-08-17) replaces the flat
    `settings.*` reads that used to sit here directly - `style=None`
    (every Timeline predating this field) resolves to EXACTLY the same
    three numbers those flat reads always produced, verified directly
    against `settings` before this call site was touched.

    No special-case for `produced_by == NARRATION` here (M8 hardening,
    2026-08-16 - the fix for "A26 is a deadlock in practice"): that used
    to short-circuit straight to `True` because M8's NarrationStep may
    legitimately stretch a shot's reconciled duration past
    `max_shot_duration_s` (the cap is a planning heuristic, narration is
    real), but checking the CURRENT version's `produced_by` only ever
    protected the one version immediately after narration - any later
    version (a human override, a music retry, a narration-voice retry)
    fell straight back out of it and re-failed against measured reality.
    `validate_constraints` itself now reads
    `timeline.metadata.narration_locked` - a flag that survives every
    later version, not just this one - to decide whether shot-duration
    bounds still apply, so this call is correct uniformly, forever,
    without this function needing to know anything about narration at
    all."""
    bundle = _constraint_bundle(timeline)
    return timeline.validate_constraints(
        max_video_duration_s=bundle.max_video_duration_s,
        max_shots_per_project=bundle.max_shots_per_project,
        min_shot_duration_s=bundle.min_shot_duration_s,
        max_shot_duration_s=bundle.max_shot_duration_s,
        max_scenes=bundle.max_scenes,
    )


def _constraint_bundle(timeline: Timeline, *, script: str | None = None) -> ConstraintBundle:
    """One resolver, one N. Concatenated scene narration is the script
    once scenes exist; the uploaded script is used before that."""
    text = script or "".join(s.narration_text for s in timeline.scenes)
    n = len(split_narration_fragments(text)) if text else None
    return resolve_constraint_bundle(timeline.metadata.render_style, n_fragments=n)


def _is_fully_planned(timeline: Timeline) -> bool:
    if not timeline.scenes:
        return False
    shots = timeline.all_shots()
    if not shots:
        return False
    if any(shot.asset_plan is None for shot in shots):
        return False
    # Structural completeness alone isn't enough: a timeline can be fully
    # populated (every scene has shots, every shot has an asset_plan) and
    # still violate a D7 constraint (e.g. duplicate shot ids across
    # scenes). Without this check, is_satisfied() would return True for a
    # timeline that already failed validate_constraints() once, so a
    # retried run() call would skip straight past this step - engine.run()
    # only calls step.run() when is_satisfied() is False - carrying the
    # broken timeline forward into asset resolution instead of failing
    # loudly again.
    return not _validate_against_style(timeline)


class GenerateTimelineStep:
    name = "generate_timeline"
    retryable = True
    max_attempts = 3

    async def is_satisfied(self, ctx: RunContext) -> bool:
        active = await ctx.timeline_service.get_active(ctx.project_id)
        # An empty v1 (create_initial, before any planner has run) does
        # NOT satisfy this step - a crash between the two calls must not
        # look like "already done" on resume.
        return active is not None and _is_fully_planned(active)

    async def run(self, ctx: RunContext) -> StepResult:
        project = await ctx.repo.get(ctx.project_id)
        if project is None or not project.script:
            return StepResult(outcome="failed", error="project has no script uploaded")

        try:
            if await ctx.timeline_service.get_active(ctx.project_id) is None:
                await ctx.timeline_service.create_initial(
                    ctx.project_id, project.script, render_style=project.render_style
                )

            if settings.dry_run:
                await self._run_fake(ctx, script=project.script)
            else:
                await self._run_real(ctx, script=project.script)
        except TransientError as exc:
            return StepResult(outcome="retry", error=str(exc))
        except Exception as exc:  # noqa: BLE001 - provider call boundary
            return StepResult(outcome="failed", error=str(exc))

        timeline = await ctx.timeline_service.get_active(ctx.project_id)
        assert timeline is not None
        # R1 fix (motion_new_styles_and_long_form_videos.md §13.1, 2026-08-18):
        # now the SAME function `_is_fully_planned` uses, so this gate and
        # the resume check can no longer disagree about what a style
        # authorises - see `_validate_against_style`'s own docstring for
        # the bug this closes.
        violations = _validate_against_style(timeline)
        if violations:
            return StepResult(
                outcome="failed", error=f"timeline violates creative constraints: {violations}"
            )
        return StepResult(outcome="ok")

    async def _run_fake(self, ctx: RunContext, *, script: str) -> None:
        timeline = await ctx.timeline_service.get_active(ctx.project_id)
        assert timeline is not None
        if timeline.scenes:
            return  # already filled by a prior attempt

        fixture = await FakeTimelinePlanner().plan(project_id=ctx.project_id, script=script)
        if fixture.sfx_plan is None:
            fixture.sfx_plan = default_sfx_plan()
        await ctx.timeline_service.append_version(
            ctx.project_id,
            produced_by=ProducedBy.SHOT_PLANNER,
            transform=lambda _base: fixture,
            owns=_FAKE_PLANNER_OWNS,
        )

    async def _run_real(self, ctx: RunContext, *, script: str) -> None:
        provider = OpenAIPlanningProvider()
        llm_call_repo = LlmCallRepository(ctx.session)

        timeline = await ctx.timeline_service.get_active(ctx.project_id)
        assert timeline is not None

        if not timeline.creative_context.tone or timeline.music_plan is None:
            creative_context, music_plan = await DirectorPlanner(provider, llm_call_repo).plan(
                project_id=ctx.project_id, script=script
            )

            def _apply_director(base: Timeline) -> Timeline:
                base.creative_context = creative_context
                base.music_plan = music_plan
                if base.sfx_plan is None:
                    base.sfx_plan = default_sfx_plan()
                return base

            await ctx.timeline_service.append_version(
                ctx.project_id,
                produced_by=ProducedBy.DIRECTOR,
                transform=_apply_director,
                owns=frozenset({"creative_context", "music_plan", "sfx_plan"}),
            )
            timeline = await ctx.timeline_service.get_active(ctx.project_id)
            assert timeline is not None

        if not timeline.scenes:
            bundle = _constraint_bundle(timeline, script=script)
            scenes = await ScenePlanner(provider, llm_call_repo).plan(
                project_id=ctx.project_id,
                script=script,
                creative_context=timeline.creative_context,
                max_scenes=bundle.max_scenes,
                max_video_duration_s=bundle.max_video_duration_s,
            )

            def _apply_scenes(base: Timeline) -> Timeline:
                base.scenes = scenes
                return base

            await ctx.timeline_service.append_version(
                ctx.project_id,
                produced_by=ProducedBy.SCENE_PLANNER,
                transform=_apply_scenes,
                owns=frozenset({"scenes"}),
            )
            timeline = await ctx.timeline_service.get_active(ctx.project_id)
            assert timeline is not None

        if any(not scene.shots for scene in timeline.scenes):
            bundle = _constraint_bundle(timeline, script=script)
            min_shot_duration_s = bundle.min_shot_duration_s
            max_shot_duration_s = bundle.max_shot_duration_s
            max_shots_per_project = bundle.max_shots_per_project
            planned_scenes = await ShotPlanner(provider, llm_call_repo).plan(
                project_id=ctx.project_id,
                scenes=timeline.scenes,
                creative_context=timeline.creative_context,
                min_shot_duration_s=min_shot_duration_s,
                max_shot_duration_s=max_shot_duration_s,
                max_shots_per_project=max_shots_per_project,
                render_style=timeline.metadata.render_style,
            )
            total_duration_s = compute_timeline_duration(
                [shot for scene in planned_scenes for shot in scene.shots]
            )

            def _apply_shots(base: Timeline) -> Timeline:
                base.scenes = planned_scenes
                base.metadata.total_duration_s = total_duration_s
                return base

            await ctx.timeline_service.append_version(
                ctx.project_id,
                produced_by=ProducedBy.SHOT_PLANNER,
                transform=_apply_shots,
                owns=frozenset({"scenes", "metadata"}),
            )
            timeline = await ctx.timeline_service.get_active(ctx.project_id)
            assert timeline is not None

        if any(shot.asset_plan is None for shot in timeline.all_shots()):
            bundle = _constraint_bundle(timeline, script=script)
            planned_scenes = await AssetPlanner(provider, llm_call_repo).plan(
                project_id=ctx.project_id,
                scenes=timeline.scenes,
                max_video_shots_per_project=bundle.max_video_shots_per_project,
            )

            def _apply_assets(base: Timeline) -> Timeline:
                base.scenes = planned_scenes
                return base

            await ctx.timeline_service.append_version(
                ctx.project_id,
                produced_by=ProducedBy.ASSET_PLANNER,
                transform=_apply_assets,
                owns=frozenset({"scenes"}),
            )
