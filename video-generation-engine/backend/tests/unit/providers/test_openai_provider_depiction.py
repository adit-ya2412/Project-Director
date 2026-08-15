"""`OpenAIPlanningProvider.check_depiction` (M6.5, A16 -> A30 -> A30a) -
the depiction-verification vision call, mirroring
test_openai_provider_vision.py's pattern exactly (a hand-rolled fake
`AsyncOpenAI`-shaped client, no real network/API key)."""

from dataclasses import dataclass, field

import httpx
import openai
import pytest

from app.core.errors import PermanentError, TransientError
from app.providers.base import DepictionCheckRequest, DepictionVerdict
from app.providers.openai_provider import OpenAIPlanningProvider


@dataclass
class _FakeMessage:
    parsed: DepictionVerdict | None
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


def _request() -> DepictionCheckRequest:
    return DepictionCheckRequest(
        image=b"\xff\xd8fakejpeg",
        image_content_type="image/jpeg",
        shot_prompt="the Leuna-Werke synthetic fuel plant, 1943",
        search_subject="Leuna Werke",
    )


async def test_check_depiction_returns_the_parsed_verdict():
    verdict = DepictionVerdict(confidently_wrong=False, reason="a plausible industrial plant")
    fake_client = _FakeAsyncOpenAI(_FakeCompletion(choices=[_FakeChoice(_FakeMessage(verdict))]))
    provider = OpenAIPlanningProvider(client=fake_client)

    completion = await provider.check_depiction(_request())

    assert completion.parsed == verdict
    assert completion.model == "fake-vision-model"
    assert completion.input_tokens == 10
    assert completion.output_tokens == 5


async def test_check_depiction_sends_the_image_and_search_subject():
    verdict = DepictionVerdict(confidently_wrong=False, reason="")
    fake_client = _FakeAsyncOpenAI(_FakeCompletion(choices=[_FakeChoice(_FakeMessage(verdict))]))
    provider = OpenAIPlanningProvider(client=fake_client)

    await provider.check_depiction(_request())

    call = fake_client.chat.completions.calls[0]
    user_message = call["messages"][1]
    content_types = [part["type"] for part in user_message["content"]]
    assert "image_url" in content_types
    assert "text" in content_types
    image_part = next(p for p in user_message["content"] if p["type"] == "image_url")
    assert image_part["image_url"]["url"].startswith("data:image/jpeg;base64,")
    text_part = next(p for p in user_message["content"] if p["type"] == "text")
    assert "Leuna Werke" in text_part["text"]
    assert "Leuna-Werke synthetic fuel plant" in text_part["text"]


async def test_check_depiction_raises_permanent_error_on_refusal():
    fake_client = _FakeAsyncOpenAI(
        _FakeCompletion(choices=[_FakeChoice(_FakeMessage(parsed=None, refusal="I can't help"))])
    )
    provider = OpenAIPlanningProvider(client=fake_client)

    with pytest.raises(PermanentError, match="refused"):
        await provider.check_depiction(_request())


async def test_check_depiction_maps_rate_limit_to_transient_error():
    fake_response = httpx.Response(
        429, request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    )
    error = openai.RateLimitError("rate limited", response=fake_response, body=None)
    fake_client = _FakeAsyncOpenAI(error)
    provider = OpenAIPlanningProvider(client=fake_client)

    with pytest.raises(TransientError):
        await provider.check_depiction(_request())
