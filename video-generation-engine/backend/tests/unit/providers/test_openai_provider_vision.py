"""`OpenAIPlanningProvider.check_constraints` (M6.5, A12) - the vision-
capable structured-output call. No real network/API key: a hand-rolled
fake stand-in for the `AsyncOpenAI` client's `.chat.completions.parse`
shape is injected via the same constructor DI `OpenAIPlanningProvider`
already supports, mirroring the pattern used for `fal_client.AsyncClient`
in test_fal_queue.py - only the SDK-calling client is faked, the real
provider code (message building, response parsing, error mapping) runs
for real."""

from dataclasses import dataclass, field

import httpx
import openai
import pytest

from app.core.errors import PermanentError, TransientError
from app.providers.base import ConstraintCheckRequest, ConstraintVerdict
from app.providers.openai_provider import OpenAIPlanningProvider


@dataclass
class _FakeMessage:
    parsed: ConstraintVerdict | None
    refusal: str | None = None

    def model_dump(self, mode: str = "json") -> dict:
        return {
            "parsed": self.parsed.model_dump(mode=mode) if self.parsed else None,
            "refusal": self.refusal,
        }


@dataclass
class _FakeChoice:
    message: _FakeMessage


@dataclass
class _FakeUsage:
    prompt_tokens: int
    completion_tokens: int


@dataclass
class _FakeCompletion:
    choices: list[_FakeChoice]
    model: str = "fake-vision-model"
    usage: _FakeUsage | None = field(default_factory=lambda: _FakeUsage(10, 5))


class _FakeCompletions:
    def __init__(self, response) -> None:
        self._response = response
        self.calls: list[dict] = []

    async def parse(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


class _FakeChat:
    def __init__(self, completions: _FakeCompletions) -> None:
        self.completions = completions


class _FakeAsyncOpenAI:
    def __init__(self, response) -> None:
        self.chat = _FakeChat(_FakeCompletions(response))


def _request() -> ConstraintCheckRequest:
    return ConstraintCheckRequest(
        image=b"\xff\xd8fakejpeg",
        image_content_type="image/jpeg",
        shot_prompt="a wartime factory",
        constraints=["no Nazi symbols", "no AI faces of real historical figures"],
    )


async def test_check_constraints_returns_the_parsed_verdict():
    verdict = ConstraintVerdict(violated=False, violated_constraint="", reason="")
    fake_client = _FakeAsyncOpenAI(_FakeCompletion(choices=[_FakeChoice(_FakeMessage(verdict))]))
    provider = OpenAIPlanningProvider(client=fake_client)

    completion = await provider.check_constraints(_request())

    assert completion.parsed == verdict
    assert completion.model == "fake-vision-model"
    assert completion.input_tokens == 10
    assert completion.output_tokens == 5


async def test_check_constraints_sends_the_image_and_constraints():
    verdict = ConstraintVerdict(violated=False, violated_constraint="", reason="")
    fake_client = _FakeAsyncOpenAI(_FakeCompletion(choices=[_FakeChoice(_FakeMessage(verdict))]))
    provider = OpenAIPlanningProvider(client=fake_client)

    await provider.check_constraints(_request())

    call = fake_client.chat.completions.calls[0]
    user_message = call["messages"][1]
    content_types = [part["type"] for part in user_message["content"]]
    assert "image_url" in content_types
    assert "text" in content_types
    image_part = next(p for p in user_message["content"] if p["type"] == "image_url")
    assert image_part["image_url"]["url"].startswith("data:image/jpeg;base64,")
    text_part = next(p for p in user_message["content"] if p["type"] == "text")
    assert "no Nazi symbols" in text_part["text"]
    assert "a wartime factory" in text_part["text"]


async def test_check_constraints_never_logs_the_raw_image_bytes():
    """The `llm_call` audit row (populated by the caller from
    `StructuredCompletion.request`) must not balloon with a base64 image
    copy - the bytes already live on disk via `GeneratedClip`."""
    verdict = ConstraintVerdict(violated=False, violated_constraint="", reason="")
    fake_client = _FakeAsyncOpenAI(_FakeCompletion(choices=[_FakeChoice(_FakeMessage(verdict))]))
    provider = OpenAIPlanningProvider(client=fake_client)

    completion = await provider.check_constraints(_request())

    assert "image" not in str(completion.request).lower() or "base64" not in str(completion.request)


async def test_check_constraints_raises_permanent_error_on_refusal():
    fake_client = _FakeAsyncOpenAI(
        _FakeCompletion(choices=[_FakeChoice(_FakeMessage(parsed=None, refusal="I can't help"))])
    )
    provider = OpenAIPlanningProvider(client=fake_client)

    with pytest.raises(PermanentError, match="refused"):
        await provider.check_constraints(_request())


async def test_check_constraints_maps_rate_limit_to_transient_error():
    fake_response = httpx.Response(
        429, request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    )
    error = openai.RateLimitError("rate limited", response=fake_response, body=None)
    fake_client = _FakeAsyncOpenAI(error)
    provider = OpenAIPlanningProvider(client=fake_client)

    with pytest.raises(TransientError):
        await provider.check_constraints(_request())
