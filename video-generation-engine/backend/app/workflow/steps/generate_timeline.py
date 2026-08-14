"""Step 1: script -> Timeline.

Stand-in for Director -> Scene Planner -> Shot Planner -> Asset Planner
(M5): the fake planner fills everything in one shot, but it goes through
`TimelineService.append_version` exactly like a real planner will, so
this step doesn't change shape when M5 lands - only its innards do.
"""

from app.core.config import settings
from app.core.errors import TransientError
from app.providers.fakes.llm import FakeTimelinePlanner
from app.schemas.timeline import ProducedBy
from app.workflow.context import RunContext
from app.workflow.step import StepResult

_FAKE_PLANNER_OWNS = frozenset({"metadata", "creative_context", "music_plan", "scenes"})


class GenerateTimelineStep:
    name = "generate_timeline"
    retryable = True
    max_attempts = 3

    async def is_satisfied(self, ctx: RunContext) -> bool:
        active = await ctx.timeline_service.get_active(ctx.project_id)
        # An empty v1 (create_initial, before append_version has run) does
        # NOT satisfy this step - a crash between the two calls must not
        # look like "already done" on resume.
        return active is not None and len(active.scenes) > 0

    async def run(self, ctx: RunContext) -> StepResult:
        project = await ctx.repo.get(ctx.project_id)
        if project is None or not project.script:
            return StepResult(outcome="failed", error="project has no script uploaded")

        try:
            fixture = await FakeTimelinePlanner().plan(
                project_id=ctx.project_id, script=project.script
            )
        except TransientError as exc:
            return StepResult(outcome="retry", error=str(exc))
        except Exception as exc:  # noqa: BLE001 - provider call boundary
            return StepResult(outcome="failed", error=str(exc))

        violations = fixture.validate_constraints(
            max_video_duration_s=settings.max_video_duration_s,
            max_shots_per_project=settings.max_shots_per_project,
            min_shot_duration_s=settings.min_shot_duration_s,
            max_shot_duration_s=settings.max_shot_duration_s,
            max_scenes=settings.max_scenes,
        )
        if violations:
            return StepResult(
                outcome="failed", error=f"timeline violates creative constraints: {violations}"
            )

        # Idempotent across retries/resumes: v1 may already exist from a
        # prior attempt that crashed before append_version ran.
        if await ctx.timeline_service.get_active(ctx.project_id) is None:
            await ctx.timeline_service.create_initial(ctx.project_id, project.script)

        await ctx.timeline_service.append_version(
            ctx.project_id,
            produced_by=ProducedBy.SHOT_PLANNER,
            transform=lambda _base: fixture,
            owns=_FAKE_PLANNER_OWNS,
        )
        return StepResult(outcome="ok")
