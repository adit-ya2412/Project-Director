"""ElevenLabsNarrationProvider tests via `httpx.MockTransport` - no real
network, and no paid API calls (real-API verification is a separate,
manually-triggered concern per the Testing Strategy). Exercises the real
request-building, response-parsing, alignment-choice, and error-mapping
code."""

import base64
import json

import httpx
import pytest

from app.core.config import settings
from app.core.errors import PermanentError, TransientError
from app.providers.base import NarrationRequest
from app.providers.elevenlabs import ElevenLabsNarrationProvider, compute_narration_content_hash

_REQUEST = NarrationRequest(
    text="Germany possessed abundant coal, but lacked domestic oil reserves.",
    voice_id="voice_123",
    model="eleven_multilingual_v2",
    output_format="mp3_44100_128",
    scene_id="sc_01",
)


def _elevenlabs_response(*, audio: bytes = b"fake-mp3-bytes") -> dict:
    return {
        "audio_base64": base64.b64encode(audio).decode("ascii"),
        "alignment": {
            "characters": ["G", "e", "r"],
            "character_start_times_seconds": [0.0, 0.1, 0.2],
            "character_end_times_seconds": [0.1, 0.2, 0.3],
        },
        "normalized_alignment": {
            # Deliberately different from `alignment` above, so a test can
            # prove the provider picked the right one rather than the two
            # happening to look alike.
            "characters": ["G", "e", "r", "m", "a", "n", "y"],
            "character_start_times_seconds": [0.0, 0.05, 0.1, 0.15, 0.2, 0.25, 0.3],
            "character_end_times_seconds": [0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.35],
        },
    }


async def test_synthesize_decodes_audio_and_returns_character_count(monkeypatch):
    monkeypatch.setattr(settings, "elevenlabs_api_key", "fake-key")

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["xi-api-key"] == "fake-key"
        assert request.url.params["output_format"] == "mp3_44100_128"
        return httpx.Response(200, json=_elevenlabs_response(audio=b"real-audio-bytes"))

    provider = ElevenLabsNarrationProvider(transport=httpx.MockTransport(handler))
    result = await provider.synthesize(_REQUEST)

    assert result.content == b"real-audio-bytes"
    assert result.character_count == len(_REQUEST.text)


async def test_synthesize_sends_voice_id_in_url_and_model_in_body(monkeypatch):
    monkeypatch.setattr(settings, "elevenlabs_api_key", "fake-key")
    seen_urls = []
    seen_bodies = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen_urls.append(str(request.url).split("?")[0])
        seen_bodies.append(json.loads(request.content))
        return httpx.Response(200, json=_elevenlabs_response())

    provider = ElevenLabsNarrationProvider(transport=httpx.MockTransport(handler))
    await provider.synthesize(_REQUEST)

    assert seen_urls == ["https://api.elevenlabs.io/v1/text-to-speech/voice_123/with-timestamps"]
    assert seen_bodies[0]["text"] == _REQUEST.text
    assert seen_bodies[0]["model_id"] == "eleven_multilingual_v2"
    # Default speed 1.0 is omitted so the pre-R8 body stays byte-identical.
    assert "voice_settings" not in seen_bodies[0]
    # Default language_code (None) is omitted the same way.
    assert "language_code" not in seen_bodies[0]


async def test_synthesize_sends_language_code_when_set(monkeypatch):
    monkeypatch.setattr(settings, "elevenlabs_api_key", "fake-key")
    seen_bodies = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen_bodies.append(json.loads(request.content))
        return httpx.Response(200, json=_elevenlabs_response())

    provider = ElevenLabsNarrationProvider(transport=httpx.MockTransport(handler))
    await provider.synthesize(
        NarrationRequest(
            text=_REQUEST.text,
            voice_id=_REQUEST.voice_id,
            model=_REQUEST.model,
            output_format=_REQUEST.output_format,
            scene_id=_REQUEST.scene_id,
            language_code="hi",
        )
    )

    assert seen_bodies[0]["language_code"] == "hi"


async def test_synthesize_never_sends_speed_to_the_api(monkeypatch):
    """2026-08-24: voice_settings.speed is a documented no-op on
    eleven_v3 (live-checked - see narration_tempo.py's own docstring),
    so pacing moved to ffmpeg post-processing instead. `request.speed`
    must never reach the HTTP body regardless of its value - sending it
    AND applying narration_tempo would double the effect on any model
    where it does still work."""
    monkeypatch.setattr(settings, "elevenlabs_api_key", "fake-key")
    seen_bodies = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen_bodies.append(json.loads(request.content))
        return httpx.Response(200, json=_elevenlabs_response())

    provider = ElevenLabsNarrationProvider(transport=httpx.MockTransport(handler))
    await provider.synthesize(
        NarrationRequest(
            text=_REQUEST.text,
            voice_id=_REQUEST.voice_id,
            model=_REQUEST.model,
            output_format=_REQUEST.output_format,
            scene_id=_REQUEST.scene_id,
            speed=1.2,
        )
    )

    assert "voice_settings" not in seen_bodies[0]


async def test_synthesize_persists_raw_alignment_never_normalized(monkeypatch):
    monkeypatch.setattr(settings, "elevenlabs_api_key", "fake-key")

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_elevenlabs_response())

    provider = ElevenLabsNarrationProvider(transport=httpx.MockTransport(handler))
    result = await provider.synthesize(_REQUEST)

    # The raw `alignment` has 3 characters; `normalized_alignment` (never
    # used) has 7 - if the provider picked the wrong one, this length
    # would give it away immediately.
    assert result.alignment["characters"] == ["G", "e", "r"]
    assert result.alignment["character_start_times_seconds"] == [0.0, 0.1, 0.2]
    assert result.alignment["character_end_times_seconds"] == [0.1, 0.2, 0.3]


async def test_synthesize_without_api_key_raises_permanent_error(monkeypatch):
    monkeypatch.setattr(settings, "elevenlabs_api_key", None)
    provider = ElevenLabsNarrationProvider()
    with pytest.raises(PermanentError, match="ELEVENLABS_API_KEY"):
        await provider.synthesize(_REQUEST)


async def test_synthesize_maps_401_to_permanent_error(monkeypatch):
    monkeypatch.setattr(settings, "elevenlabs_api_key", "bad-key")

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="unauthorized")

    provider = ElevenLabsNarrationProvider(transport=httpx.MockTransport(handler))
    with pytest.raises(PermanentError, match="rejected the API key"):
        await provider.synthesize(_REQUEST)


async def test_synthesize_maps_402_to_permanent_error(monkeypatch):
    """402 Payment Required means the account is out of credits - retrying
    burns three attempts and backoff to arrive at the same answer, so it
    must be permanent. Hit for real on the first live Hindi run."""
    monkeypatch.setattr(settings, "elevenlabs_api_key", "fake-key")

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(402, text="payment required")

    provider = ElevenLabsNarrationProvider(transport=httpx.MockTransport(handler))
    with pytest.raises(PermanentError, match="402"):
        await provider.synthesize(_REQUEST)


async def test_synthesize_maps_unexpected_4xx_to_permanent_error(monkeypatch):
    """Any 4xx other than 429 is this caller's request being wrong or
    unauthorised - repeating it unchanged cannot help."""
    monkeypatch.setattr(settings, "elevenlabs_api_key", "fake-key")

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, text="unprocessable")

    provider = ElevenLabsNarrationProvider(transport=httpx.MockTransport(handler))
    with pytest.raises(PermanentError):
        await provider.synthesize(_REQUEST)


async def test_synthesize_maps_429_to_transient_error(monkeypatch):
    monkeypatch.setattr(settings, "elevenlabs_api_key", "fake-key")

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="rate limited")

    provider = ElevenLabsNarrationProvider(transport=httpx.MockTransport(handler))
    with pytest.raises(TransientError):
        await provider.synthesize(_REQUEST)


async def test_synthesize_maps_5xx_to_transient_error(monkeypatch):
    monkeypatch.setattr(settings, "elevenlabs_api_key", "fake-key")

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="server error")

    provider = ElevenLabsNarrationProvider(transport=httpx.MockTransport(handler))
    with pytest.raises(TransientError):
        await provider.synthesize(_REQUEST)


async def test_synthesize_raises_permanent_error_on_missing_alignment(monkeypatch):
    monkeypatch.setattr(settings, "elevenlabs_api_key", "fake-key")

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"audio_base64": base64.b64encode(b"x").decode()})

    provider = ElevenLabsNarrationProvider(transport=httpx.MockTransport(handler))
    with pytest.raises(PermanentError, match="alignment"):
        await provider.synthesize(_REQUEST)


def test_content_hash_is_stable_and_sensitive_to_every_input():
    base_hash = compute_narration_content_hash(
        text="hello", voice_id="v1", model="m1", output_format="o1"
    )
    assert base_hash == compute_narration_content_hash(
        text="hello", voice_id="v1", model="m1", output_format="o1"
    )
    assert base_hash != compute_narration_content_hash(
        text="hello!", voice_id="v1", model="m1", output_format="o1"
    )
    assert base_hash != compute_narration_content_hash(
        text="hello", voice_id="v2", model="m1", output_format="o1"
    )
    assert base_hash != compute_narration_content_hash(
        text="hello", voice_id="v1", model="m2", output_format="o1"
    )
    assert base_hash != compute_narration_content_hash(
        text="hello", voice_id="v1", model="m1", output_format="o2"
    )
    # Default 1.0 (and an explicit 1.0) keep the four-value pre-R8 key.
    assert base_hash == compute_narration_content_hash(
        text="hello", voice_id="v1", model="m1", output_format="o1", speed=1.0
    )
    assert base_hash != compute_narration_content_hash(
        text="hello", voice_id="v1", model="m1", output_format="o1", speed=1.2
    )
    # Default None keeps the pre-existing key (every row narrated before
    # language_code existed); an actual hint changes it.
    assert base_hash == compute_narration_content_hash(
        text="hello", voice_id="v1", model="m1", output_format="o1", language_code=None
    )
    assert base_hash != compute_narration_content_hash(
        text="hello", voice_id="v1", model="m1", output_format="o1", language_code="hi"
    )


async def test_fake_provider_scales_alignment_with_speed():
    """DRY_RUN must not keep documentary-paced fake speech on a 1.2 style."""
    from app.providers.fakes.narration import FakeNarrationProvider

    slow = await FakeNarrationProvider().synthesize(_REQUEST)
    fast = await FakeNarrationProvider().synthesize(
        NarrationRequest(
            text=_REQUEST.text,
            voice_id=_REQUEST.voice_id,
            model=_REQUEST.model,
            output_format=_REQUEST.output_format,
            scene_id=_REQUEST.scene_id,
            speed=1.2,
        )
    )
    slow_end = slow.alignment["character_end_times_seconds"][-1]
    fast_end = fast.alignment["character_end_times_seconds"][-1]
    assert slow_end / fast_end == pytest.approx(1.2)
