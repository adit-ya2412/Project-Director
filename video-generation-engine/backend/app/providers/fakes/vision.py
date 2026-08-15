"""Fake vision-constraint provider (M6.5, A12). Returns a configurable,
canned verdict per call - no network, no OpenAI. Not the DRY_RUN path
itself (DRY_RUN never constructs any vision provider at all, real or
fake - see `ResolveAssetsStep`); this is the real-mode unit/integration
test double, same discipline as `FakeImageProvider`/`FakeAssetProvider`
(implementation guide section 4.1: fake first, always - and keep it
forever)."""

from app.providers.base import (
    ConstraintCheckRequest,
    ConstraintVerdict,
    DepictionCheckRequest,
    DepictionVerdict,
    StructuredCompletion,
)

_NOT_VIOLATED = ConstraintVerdict(violated=False, violated_constraint="", reason="")
_NOT_CONFIDENTLY_WRONG = DepictionVerdict(confidently_wrong=False, reason="")


class FakeVisionConstraintProvider:
    name = "fake_vision"

    def __init__(
        self,
        verdicts: list[ConstraintVerdict] | None = None,
        depiction_verdicts: list[DepictionVerdict] | None = None,
    ) -> None:
        # Popped one per call, in submitted order, so a test can script an
        # exact sequence (e.g. [violated, violated, not_violated] to prove
        # a specific retry count) - the last entry repeats if a test calls
        # this more times than it scripted, rather than raising IndexError
        # for tests that only care about the steady-state verdict. Same
        # discipline for `depiction_verdicts` (M6.5, A30) - a separate
        # list, since the two checks are unrelated questions with
        # independent call counts.
        self._verdicts = list(verdicts) if verdicts else [_NOT_VIOLATED]
        self._depiction_verdicts = (
            list(depiction_verdicts) if depiction_verdicts else [_NOT_CONFIDENTLY_WRONG]
        )
        self.calls: list[ConstraintCheckRequest] = []
        self.depiction_calls: list[DepictionCheckRequest] = []

    async def check_constraints(self, request: ConstraintCheckRequest) -> StructuredCompletion:
        self.calls.append(request)
        verdict = self._verdicts.pop(0) if len(self._verdicts) > 1 else self._verdicts[0]
        return StructuredCompletion(
            parsed=verdict,
            model="fake-vision-model",
            request={"shot_prompt": request.shot_prompt, "constraints": request.constraints},
            response=verdict.model_dump(mode="json"),
            input_tokens=1,
            output_tokens=1,
        )

    async def check_depiction(self, request: DepictionCheckRequest) -> StructuredCompletion:
        self.depiction_calls.append(request)
        verdict = (
            self._depiction_verdicts.pop(0)
            if len(self._depiction_verdicts) > 1
            else self._depiction_verdicts[0]
        )
        return StructuredCompletion(
            parsed=verdict,
            model="fake-vision-model",
            request={
                "shot_prompt": request.shot_prompt,
                "search_subject": request.search_subject,
            },
            response=verdict.model_dump(mode="json"),
            input_tokens=1,
            output_tokens=1,
        )
