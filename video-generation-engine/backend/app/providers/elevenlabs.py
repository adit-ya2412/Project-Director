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


# Live-checked 2026-08-20 against POST .../with-timestamps on
# eleven_multilingual_v2: voice_settings.speed was accepted there, 1.2
# was in range, and alignment timestamps scaled with it (parent plan
# §2.1 / R8). Re-checked live 2026-08-24 against eleven_v3 (the current
# default model): speed values from 0.5 to 3.0 against identical text
# produced durations with NO monotonic relationship to the requested
# value - not weaker, non-functional. `synthesize` below no longer
# sends it to the API at all; `app/renderer/narration_tempo.py` applies
# it deterministically via ffmpeg instead, on any model.
#
# The upper bound moved from 1.2 to 1.4 the same day, for a DIFFERENT
# reason than the original "ElevenLabs' published quality band" one:
# v3's own natural (unadjusted) pacing for identical text swung ~35%
# call to call in a live check (9.28s-12.56s for the same 147 chars) -
# a real retention_fast render came out sounding too slow because a
# slow natural draw, correctly multiplied by 1.2, still lands slower
# than a lucky unadjusted draw from before this fix existed. 1.4 biases
# toward staying fast even on a slow draw. Both bounds are comfortably
# inside `atempo`'s own valid 0.5-2.0 per-instance range regardless, so
# a single atempo stage always suffices.
_DEFAULT_SPEED = 1.0
_SPEED_MIN = 0.7
_SPEED_MAX = 1.4


def canonical_narration_speed(speed: float) -> float:
    """Clamp and round so the value we hash is the value we send."""
    return round(min(_SPEED_MAX, max(_SPEED_MIN, float(speed))), 3)


def compute_narration_content_hash(
    *,
    text: str,
    voice_id: str,
    model: str,
    output_format: str,
    speed: float = _DEFAULT_SPEED,
    language_code: str | None = None,
) -> str:
    """The cache key for a synthesis request - also the `{content_hash}`
    half of the D3 storage path `{project}/narration/{content_hash}.mp3`.

    Hashes the REQUEST, not the response audio bytes, exactly like
    `generated_clip.prompt_hash` hashes the prompt rather than the
    generated image: an identical request must never be paid for twice,
    and the request is fully determined by these values before any
    network call happens.

    `speed` is part of the key (parent plan §2.1 / R8). A speed that
    reaches the API but not this hash silently serves wrong-speed audio
    on the second run; Track C's disk-fallback would then restore that
    wrong-speed mp3 rather than re-synthesise. Default 1.0 is omitted
    from the digest so existing four-value rows (every project narrated
    before R8) remain cache hits at the API default.

    `language_code` (2026-08-24) follows the same convention: None is
    omitted from the digest so every pre-existing row (synthesised
    before this field existed) stays a cache hit, and only a project
    that actually sets a language hint pays for a fresh call.
    """
    digest_input = f"{text}|{voice_id}|{model}|{output_format}"
    canonical = canonical_narration_speed(speed)
    if canonical != _DEFAULT_SPEED:
        digest_input += f"|{canonical:.3f}"
    if language_code:
        digest_input += f"|{language_code}"
    return hashlib.sha256(digest_input.encode()).hexdigest()


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
        payload: dict = {"text": request.text, "model_id": request.model}
        # `request.speed` is deliberately NOT sent as `voice_settings.
        # speed` (2026-08-24) - see this module's own comment above on
        # why: non-functional on the current default model, and sending
        # it AND applying `narration_tempo.apply_narration_tempo`
        # afterward would double the effect on any model where it does
        # work. `request.speed` still flows into the content hash
        # (below callers) and `FakeNarrationProvider`'s own DRY_RUN
        # timing - only the real HTTP request stops asking for it.
        if request.language_code:
            payload["language_code"] = request.language_code

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
            status = exc.response.status_code
            if status in (401, 403):
                raise PermanentError(f"elevenlabs rejected the API key: {status}") from exc
            if status == 402:
                raise PermanentError(
                    "elevenlabs returned 402 Payment Required - the account is out of "
                    "credits or the plan does not cover this request. Retrying cannot "
                    "fix this; top up the account at https://elevenlabs.io/app/subscription"
                ) from exc
            # 429 is the only 4xx worth retrying (rate limit, self-clearing).
            # Every other 4xx is the caller's own request being wrong or
            # unauthorised - a retry just repeats the same mistake three times
            # with backoff, delaying a clear failure. 5xx is the server's
            # problem and genuinely may pass.
            if status == 429 or status >= 500:
                raise TransientError(f"elevenlabs synthesis returned {status}") from exc
            raise PermanentError(f"elevenlabs synthesis failed: {exc}") from exc

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
