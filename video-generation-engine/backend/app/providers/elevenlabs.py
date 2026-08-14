"""ElevenLabs narration provider (M8, D1). The ONLY file in the codebase
that knows about the ElevenLabs endpoint or request/response shape (ADR-003
provider firewall) - everything else depends on `NarrationProvider` in
`providers/base.py`.

Uses the *timestamped* endpoint,
`POST /v1/text-to-speech/{voice_id}/with-timestamps`, so audio and timing
data arrive together in one call - no separate forced-alignment step, and
therefore no alignment error (D1). Verified against the live API docs
(not guessed) on 2026-08-15:

- The response body is JSON, not raw audio bytes: `audio_base64` is
  base64-encoded audio; decode it before writing to disk or hashing.
- `output_format` is a query parameter, not a body field.
- The response carries TWO alignment objects, `alignment` and
  `normalized_alignment`, each with three parallel arrays -
  `characters`, `character_start_times_seconds`,
  `character_end_times_seconds`. Both are CHARACTER-level, never
  word-level (an earlier draft of the implementation guide assumed
  word-level timings; that was wrong about the mechanism, not the
  decision - see the guide's M8 section).
- Auth is the `xi-api-key` header, not `Authorization`.

This module persists `alignment`, never `normalized_alignment` - see
`synthesize` below for why that particular choice is load-bearing rather
than arbitrary.
"""

import base64
import hashlib

import httpx

from app.core.config import settings
from app.core.errors import PermanentError, TransientError
from app.providers.base import NarrationRequest, NarrationResult

_API_BASE_URL = "https://api.elevenlabs.io"
# A scene's narration is a handful of sentences, not a live stream - a
# generous bounded timeout is simpler and safer than a poll loop (compare
# FalImageProvider, which also treats its provider as fast-and-synchronous).
_REQUEST_TIMEOUT_S = 60.0


def compute_narration_content_hash(
    *, text: str, voice_id: str, model: str, output_format: str
) -> str:
    """The cache key for a synthesis request - also the `{content_hash}`
    half of the D3 storage path `{project}/narration/{content_hash}.mp3`.

    Hashes the REQUEST, not the response audio bytes, exactly like
    `generated_clip.prompt_hash` hashes the prompt rather than the
    generated image: an identical request must never be paid for twice,
    and the request is fully determined by these four values before any
    network call happens.
    """
    digest_input = f"{text}|{voice_id}|{model}|{output_format}".encode()
    return hashlib.sha256(digest_input).hexdigest()


class ElevenLabsNarrationProvider:
    name = "elevenlabs"

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        # `transport` is None in production (real network); tests inject
        # an `httpx.MockTransport` to exercise request/response handling
        # without a real network call - and without spending real money.
        self._transport = transport

    async def synthesize(self, request: NarrationRequest) -> NarrationResult:
        if not settings.elevenlabs_api_key:
            raise PermanentError("ELEVENLABS_API_KEY is not configured")

        url = f"{_API_BASE_URL}/v1/text-to-speech/{request.voice_id}/with-timestamps"
        params = {"output_format": request.output_format}
        payload = {"text": request.text, "model_id": request.model}

        try:
            async with httpx.AsyncClient(
                timeout=_REQUEST_TIMEOUT_S, transport=self._transport
            ) as client:
                response = await client.post(
                    url,
                    params=params,
                    json=payload,
                    headers={"xi-api-key": settings.elevenlabs_api_key},
                )
                response.raise_for_status()
                data = response.json()
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise TransientError(f"elevenlabs synthesis timed out or errored: {exc}") from exc
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (401, 403):
                raise PermanentError(
                    f"elevenlabs rejected the API key: {exc.response.status_code}"
                ) from exc
            if exc.response.status_code in (429, 500, 502, 503, 504):
                raise TransientError(
                    f"elevenlabs synthesis returned {exc.response.status_code}"
                ) from exc
            raise TransientError(f"elevenlabs synthesis failed: {exc}") from exc

        try:
            content = base64.b64decode(data["audio_base64"])
        except (KeyError, TypeError, ValueError) as exc:
            raise PermanentError(f"elevenlabs response missing valid audio_base64: {exc}") from exc

        # `alignment`, never `normalized_alignment`: the normalized variant
        # is aligned to ElevenLabs' expanded text ("1943" -> "nineteen
        # forty-three", "Dr." -> "Doctor"), so its character indices no
        # longer correspond to `request.text` - the exact text
        # `Shot.narration_span` indexes into. Using it would silently
        # desynchronise every shot whose narration contains a number or an
        # abbreviation, which on a historical documentary script is most
        # of them.
        alignment = data.get("alignment")
        if not alignment:
            raise PermanentError("elevenlabs response missing alignment data")

        return NarrationResult(
            content=content,
            alignment=alignment,
            character_count=len(request.text),
        )
