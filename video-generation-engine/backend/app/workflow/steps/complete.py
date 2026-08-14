"""Step 5: mark the project done. A distinct step (rather than folding
this into RenderStep) matches ADR-009's pipeline and gives the eventual
completion domain event its own place to live."""

from app.schemas.project import ProjectStatus
from app.workflow.context import RunContext
from app.workflow.step import StepResult


class CompleteStep:
    name = "complete"
    retryable = False
    max_attempts = 1

    async def is_satisfied(self, ctx: RunContext) -> bool:
        project = await ctx.repo.get(ctx.project_id)
        return project is not None and project.status == ProjectStatus.COMPLETED

    async def run(self, ctx: RunContext) -> StepResult:
        project = await ctx.repo.get(ctx.project_id)
        if project is None:
            return StepResult(outcome="failed", error="project vanished mid-run")
        project.status = ProjectStatus.COMPLETED
        project.error = None
        await ctx.repo.update(project)
        return StepResult(outcome="ok")
