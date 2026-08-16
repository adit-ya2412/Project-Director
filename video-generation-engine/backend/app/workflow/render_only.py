"""R3 (2026-08-16): a render-only path, structurally incapable of
invoking any paid provider.

`POST /render` (`app/api/projects.py::render_project`) is not a render
command - it resumes the ENTIRE workflow from the first unsatisfied
step, which is correct for what THAT endpoint is for, but it means the
only way to hear a mix change was to re-run the whole pipeline,
including `ResolveAssetsStep`'s paid OpenAI vision calls (R2/R3, this
same implementation-guide entry: re-rendering to hear a
`MUSIC_BED_GAIN_DB` change cost real money for exactly this reason).
`RenderStep` is documented (I5) as a pure function of the Timeline plus
already-resolved media; this module takes that claim at face value and
gives it its own door, rather than adding a `steps=` query filter to the
general trigger endpoint - see the note at the bottom of this docstring
for why a dedicated endpoint won over a filter.

## "Structurally incapable", not "checked and then trusted"

`RENDER_ONLY_STEPS` is a workflow-step LIST containing exactly two
steps: `RenderStep`, and `CompleteStep` (which only ever flips
`project.status` to COMPLETED and touches nothing else - see the
comment on the constant below for why it rides along). `WorkflowEngine
.run()` only ever iterates `self._steps` (app/workflow/engine.py) -
there is no code path by which an engine constructed from this list can
reach `GenerateTimelineStep`, `ResolveAssetsStep`, `SelectMusicStep`, or
`NarrationStep`, every one of which can touch a paid provider (directly,
or via a planner). This holds independently of whatever precondition
check runs beforehand: even a bug in `render_precondition_gap` below
could only ever let an ill-advised render through (e.g. rendering
placeholders for shots nobody resolved yet) - it could never make this
engine invoke a provider, because the provider-calling steps are simply
absent from the list it was built with. That is the actual safety
property the task asked for ("not 'unlikely to' - incapable"); the
precondition check below is a kindness, not the mechanism the guarantee
rests on.

## Why the precondition check exists anyway

Not for provider safety (the list above already guarantees that) but for
honesty: a render-only trigger on a project that never reached the real
render step yet (timeline unapproved, narration never run, shots still
unresolved) would otherwise render SOMETHING - mostly placeholders,
silently - because `RenderStep` is deliberately tolerant of missing
media (Principle 10, "failure is per-task"; see `render.py`'s own
`render_placeholder` fallback). `render_precondition_gap` re-runs the
exact same `is_satisfied` check every step ahead of render in
`DEFAULT_PIPELINE` already performs - `GenerateTimelineStep` through
`AwaitReviewStep`, every one a read-only DB query, none a provider call
even here - and returns the name of the first one still saying "not
yet". The endpoint fails loudly with that name rather than quietly
producing a video nobody asked for.

## Dedicated endpoint, not a `steps=` filter on `POST /render`

Both were considered. A query filter on the general trigger would need,
at minimum, a validated enum of allowed values and a runtime branch
choosing which step list to build from user input - the exact shape that
makes "can this ever reach a paid step" a question about validation
logic rather than about what code exists to run at all. A second,
narrow endpoint whose entire step list is a two-item, non-parameterised
constant answers that question by inspection, once, and the two
endpoints already read differently in every other way that matters (this
one 409s loudly on a project that isn't ready; `POST /render` never
does, by design - it advances the workflow instead). `POST /render/draft`
already established the "another sibling `/render/...` route for a
variant of rendering" shape in this codebase, so this is not a new
pattern being introduced, just the render-only variant of it.
"""

from app.workflow.context import RunContext
from app.workflow.engine import DEFAULT_PIPELINE
from app.workflow.step import WorkflowStep
from app.workflow.steps.complete import CompleteStep
from app.workflow.steps.render import RenderStep

# `CompleteStep` rides along for a reason that has nothing to do with
# provider safety and everything to do with not leaving the project in
# the wrong STATUS: `RenderStep.run()` sets `project.status =
# ProjectStatus.RENDERING` unconditionally (mirroring the normal
# pipeline, where `CompleteStep` always runs immediately after it and
# flips that to COMPLETED). Render-only is only ever reachable once
# `render_precondition_gap` has already confirmed every other step is
# satisfied, so a successful render here IS a completed project by
# definition - omitting `CompleteStep` would strand `project.status` at
# RENDERING forever after every render-only call, which is a real,
# user-visible bug (`GET /status` lying about a project that has, in
# fact, finished), not a cosmetic one. `CompleteStep` itself makes no
# provider call and touches nothing but `project.status` - including it
# does not weaken the "structurally incapable" guarantee this module
# exists for.
RENDER_ONLY_STEPS: list[WorkflowStep] = [RenderStep(), CompleteStep()]

# Every step name in `DEFAULT_PIPELINE` that is NOT a precondition for
# render-only: "render" is the thing being invoked, not a precondition
# for itself, and "complete" only ever marks the project COMPLETED after
# a render already happened - neither belongs in the gap check below.
_NOT_A_PRECONDITION = frozenset({"render", "complete"})


async def render_precondition_gap(ctx: RunContext) -> str | None:
    """`None` if a render is possible right now - every step ahead of
    `RenderStep` in the normal pipeline already reports `is_satisfied`.
    Otherwise the name of the first step still blocking it (e.g.
    "await_approval" if the plan itself was never approved, or
    "resolve_assets_generate" if some shot is still waiting on
    generation) - a legible reason `app/api/projects.py::render_only`
    turns into a 409, never a step this module runs itself."""
    for step in DEFAULT_PIPELINE:
        if step.name in _NOT_A_PRECONDITION:
            continue
        if not await step.is_satisfied(ctx):
            return step.name
    return None
