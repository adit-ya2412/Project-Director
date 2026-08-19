"""Shared test doubles for planner golden-file tests. A `FakePlanningProvider`
returns pre-canned, already-validated `BaseModel` instances in sequence -
no network, no real OpenAI call - matching the implementation guide's
Phase M5 advice: "golden-file tests: recorded LLM response -> planner ->
expected Timeline. Fast, free, deterministic.\""""

import asyncio

from pydantic import BaseModel

from app.providers.base import StructuredCompletion


class FakePlanningProvider:
    name = "fake"

    def __init__(self, responses: list[BaseModel]) -> None:
        self._responses = list(responses)
        self.calls: list[dict] = []
        self._lock = asyncio.Lock()

    async def structured_complete(
        self,
        *,
        system_prompt: str,
        user_content: str,
        response_model: type,
        seed: int | None = None,
    ) -> StructuredCompletion:
        async with self._lock:
            self.calls.append({"system_prompt": system_prompt, "user_content": user_content})
            parsed = None
            for i, candidate in enumerate(self._responses):
                if isinstance(candidate, response_model):
                    parsed = self._responses.pop(i)
                    break
            if parsed is None:
                parsed = self._responses.pop(0)
        return StructuredCompletion(
            parsed=parsed,
            model="fake-planning-model",
            request={"messages": [{"role": "user", "content": user_content}]},
            response=parsed.model_dump(mode="json"),
            input_tokens=42,
            output_tokens=42,
        )
