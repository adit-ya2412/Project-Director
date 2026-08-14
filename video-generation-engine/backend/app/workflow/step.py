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

# Four outcomes, not three (contrast with Command/Result's three in
# section 6.2): "awaiting_approval" is a deliberate pause, not a failure.
# The engine treats it as "stop the run cleanly", never as an error.
StepOutcome = Literal["ok", "retry", "failed", "awaiting_approval"]


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
