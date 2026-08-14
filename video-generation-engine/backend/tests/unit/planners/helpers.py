"""Shared test doubles for planner golden-file tests. A `FakePlanningProvider`
returns pre-canned, already-validated `BaseModel` instances in sequence -
no network, no real OpenAI call - matching the implementation guide's
Phase M5 advice: "golden-file tests: recorded LLM response -> planner ->
expected Timeline. Fast, free, deterministic.\""""

from pydantic import BaseModel

from app.providers.base import StructuredCompletion


class FakePlanningProvider:
    name = "fake"

    def __init__(self, responses: list[BaseModel]) -> None:
        self._responses = list(responses)
        self.calls: list[dict] = []

    async def structured_complete(
        self,
        *,
        system_prompt: str,
        user_content: str,
        response_model: type,
        seed: int | None = None,
    ) -> StructuredCompletion:
        self.calls.append({"system_prompt": system_prompt, "user_content": user_content})
        parsed = self._responses.pop(0)
        return StructuredCompletion(
            parsed=parsed,
            model="fake-planning-model",
            request={"messages": [{"role": "user", "content": user_content}]},
            response=parsed.model_dump(mode="json"),
            input_tokens=42,
            output_tokens=42,
        )
