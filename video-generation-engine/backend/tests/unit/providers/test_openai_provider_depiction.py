"""`OpenAIPlanningProvider.check_depiction` (M6.5, A16 -> A30 -> A30a) -
the depiction-verification vision call, mirroring
test_openai_provider_vision.py's pattern exactly (a hand-rolled fake
`AsyncOpenAI`-shaped client, no real network/API key)."""

import base64
import io
from dataclasses import dataclass, field

import httpx
import openai
import pytest
from PIL import Image

from app.core.config import settings
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


def _jpeg_bytes(width: int, height: int) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), color=(40, 80, 120)).save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def _data_url_image_size(data_url: str) -> tuple[int, int]:
    header, _, b64 = data_url.partition(",")
    assert header.startswith("data:image/")
    with Image.open(io.BytesIO(base64.b64decode(b64))) as im:
        return im.size


async def test_check_depiction_downscales_large_image_to_setting(monkeypatch):
    """P-OQ-15.4: longest edge capped at depiction_image_max_px (1024 held)."""
    monkeypatch.setattr(settings, "depiction_image_max_px", 1024)
    verdict = DepictionVerdict(confidently_wrong=False, reason="ok")
    fake_client = _FakeAsyncOpenAI(_FakeCompletion(choices=[_FakeChoice(_FakeMessage(verdict))]))
    provider = OpenAIPlanningProvider(client=fake_client)

    await provider.check_depiction(
        DepictionCheckRequest(
            image=_jpeg_bytes(2000, 1500),
            image_content_type="image/jpeg",
            shot_prompt="an industrial plant",
            search_subject="Leuna Werke",
        )
    )

    image_part = next(
        p for p in fake_client.chat.completions.calls[0]["messages"][1]["content"] if p["type"] == "image_url"
    )
    w, h = _data_url_image_size(image_part["image_url"]["url"])
    assert max(w, h) <= 1024
    assert max(w, h) == 1024


async def test_check_depiction_does_not_upscale_small_image(monkeypatch):
    monkeypatch.setattr(settings, "depiction_image_max_px", 1024)
    verdict = DepictionVerdict(confidently_wrong=False, reason="ok")
    fake_client = _FakeAsyncOpenAI(_FakeCompletion(choices=[_FakeChoice(_FakeMessage(verdict))]))
    provider = OpenAIPlanningProvider(client=fake_client)
    original = _jpeg_bytes(400, 300)

    await provider.check_depiction(
        DepictionCheckRequest(
            image=original,
            image_content_type="image/jpeg",
            shot_prompt="an industrial plant",
            search_subject="Leuna Werke",
        )
    )

    image_part = next(
        p for p in fake_client.chat.completions.calls[0]["messages"][1]["content"] if p["type"] == "image_url"
    )
    header, _, b64 = image_part["image_url"]["url"].partition(",")
    assert header.startswith("data:image/jpeg")
    assert base64.b64decode(b64) == original
