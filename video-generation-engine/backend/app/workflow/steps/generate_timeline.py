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
from app.core.logging import get_logger
from app.planners.asset.planner import AssetPlanner
from app.planners.director.planner import DirectorPlanner
from app.planners.fragments import split_narration_fragments
from app.planners.scene.planner import ScenePlanner
from app.planners.shot.planner import ShotPlanner
from app.providers.fakes.llm import FakeTimelinePlanner
from app.providers.openai_provider import OpenAIPlanningProvider
from app.repositories.llm_call_repository import LlmCallRepository
from app.schemas.timeline import (
    AssetPlan,
    AssetStrategy,
    PreferredMediaType,
    ProducedBy,
    Scene,
    Timeline,
)
from app.script.styles import (
    ConstraintBundle,
    PicturePath,
    resolve_constraint_bundle,
    resolve_picture_path,
)
from app.timeline.duration import compute_timeline_duration
from app.workflow.context import RunContext
from app.workflow.step import StepResult
from app.workflow.steps.select_sfx import default_sfx_plan

logger = get_logger(__name__)

_FAKE_PLANNER_OWNS = frozenset({"metadata", "creative_context", "music_plan", "sfx_plan", "scenes"})


def _force_generation_only_picture_path(scenes: list[Scene]) -> list[Scene]:
    """illustrated_faceless.md §3.2 (F1): the enforcement point for
    `resolve_picture_path(style) is PicturePath.GENERATION_ONLY`.

    Runs AFTER `AssetPlanner.plan` returns, never before and never by
    prompting it - `_build_user_content` in `app/planners/asset/
    planner.py` never sends `render_style` to the Asset Planner at all
    (verified 2026-09-04), so it has no way to know this project is
    generation-only, and telling it in its own prompt anyway would only
    usually work - see `resolve_picture_path`'s own docstring for why
    "usually" is the defect this function exists to remove.

    Overrides only the PRIMARY `asset_plan` on every shot - `strategy`
    and `fallback_chain` collapse to the single legal generation-only
    chain `[generate_image]` (a valid ascending subsequence of
    `ASSET_LADDER` by construction: one element trivially satisfies
    "ascending"), and `preferred_type` is forced to `image` so this
    stays STILLS ONLY regardless of what the Asset Planner guessed from
    the shot's camera movement - F1 has no layers, no parallax, no
    per-shot motion cost yet (that is F2+). `entity`/`search_queries`/
    `licence_requirements` are left as the Asset Planner produced them -
    harmless, since a chain of only `generate_image` never reaches the
    search/entity rungs those fields would otherwise drive (see
    `app/workflow/steps/resolve_assets.py`: a shot's fallback chain is
    walked restricted to each pass's permitted rungs, and `generate_
    image` is the only rung 5-6 pass ever reaches).

    `secondary_asset_plan` (the `split_frame` bottom panel) is
    deliberately left untouched - out of F1's scope entirely
    (illustrated_faceless.md's own DO-NOT list). The style fragment asks
    the Shot Planner not to use `split_frame` for this style at all, so
    in practice this rarely matters; if a split_frame shot slips through
    anyway, its secondary panel keeps the Asset Planner's own (possibly
    retrieval-first) plan rather than being forced generation-only.
    """

    def _generation_only(plan: AssetPlan | None) -> AssetPlan | None:
        if plan is None:
            return None
        return plan.model_copy(
            update={
                "strategy": AssetStrategy.GENERATE_IMAGE,
                "fallback_chain": [AssetStrategy.GENERATE_IMAGE],
                "preferred_type": PreferredMediaType.IMAGE,
            }
        )

    new_scenes = []
    for scene in scenes:
        new_shots = [
            shot.model_copy(update={"asset_plan": _generation_only(shot.asset_plan)})
            for shot in scene.shots
        ]
        new_scenes.append(scene.model_copy(update={"shots": new_shots}))
    return new_scenes


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
                    ctx.project_id,
                    project.script,
                    render_style=project.render_style,
                    frame_aspect=project.frame_aspect,
                    language_code=project.language_code,
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
                project_id=ctx.project_id,
                script=script,
                # RV2 "resolve once, thread explicitly" (illustrated_faceless.md
                # P-IF-F1-review3): `timeline` (loaded above at line 255-256)
                # already carries `metadata.render_style` for this project - the
                # planner must not reach into settings or the DB for it itself.
                render_style=timeline.metadata.render_style,
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
            scenes, acts = await ScenePlanner(provider, llm_call_repo).plan(
                project_id=ctx.project_id,
                script=script,
                creative_context=timeline.creative_context,
                max_scenes=bundle.max_scenes,
                max_video_duration_s=bundle.max_video_duration_s,
            )

            def _apply_scenes(base: Timeline) -> Timeline:
                base.scenes = scenes
                # A3: acts is [] on Path A, matching the empty-default
                # every pre-A3 timeline already loads with.
                base.acts = acts
                return base

            await ctx.timeline_service.append_version(
                ctx.project_id,
                produced_by=ProducedBy.SCENE_PLANNER,
                transform=_apply_scenes,
                owns=frozenset({"scenes", "acts"}),
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
                acts=timeline.acts,
                frame_aspect=timeline.metadata.frame_aspect,
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
            if resolve_picture_path(timeline.metadata.render_style) is PicturePath.GENERATION_ONLY:
                logger.info(
                    "generate_timeline.picture_path_forced_generation_only",
                    extra={
                        "project_id": ctx.project_id,
                        "render_style": timeline.metadata.render_style,
                    },
                )
                planned_scenes = _force_generation_only_picture_path(planned_scenes)

            def _apply_assets(base: Timeline) -> Timeline:
                base.scenes = planned_scenes
                return base

            await ctx.timeline_service.append_version(
                ctx.project_id,
                produced_by=ProducedBy.ASSET_PLANNER,
                transform=_apply_assets,
                owns=frozenset({"scenes"}),
            )
