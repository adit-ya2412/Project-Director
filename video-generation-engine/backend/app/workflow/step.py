"""The step contract (implementation guide, Phase M4).

Every pipeline stage - fake today, real from M5 onward - implements this
same three-member interface. `is_satisfied` is what makes a run resumable:
the engine asks "is this already done?" before ever calling `run`, so a
process that crashes mid-pipeline restarts by skipping straight past
whatever already succeeded rather than tracking a step index.
"""

from dataclasses import dataclass
from typing import Literal, Protocol

from app.workflow.context import RunContext

# Five outcomes, not three (contrast with Command/Result's three in
# section 6.2): "awaiting_approval" and "awaiting_review" (M6.5, A26/A28)
# are both deliberate pauses, not failures - the engine treats either as
# "stop the run cleanly", never as an error. They are distinct because
# they are different questions with different remedies (approve the
# creative plan, versus fix a shot that failed generation) - see
# `app/workflow/steps/await_review.py`.
StepOutcome = Literal["ok", "retry", "failed", "awaiting_approval", "awaiting_review"]


@dataclass
class StepResult:
    outcome: StepOutcome
    error: str | None = None


class WorkflowStep(Protocol):
    name: str
    retryable: bool
    max_attempts: int

    async def is_satisfied(self, ctx: RunContext) -> bool:
        """True if this step's output already exists — the engine skips
        straight past it without calling `run`."""
        ...

    async def run(self, ctx: RunContext) -> StepResult: ...
