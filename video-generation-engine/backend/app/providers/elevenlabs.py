"""ElevenLabs narration + sound-generation providers (M8/D1,
long_form_direction.md A8). The ONLY file in the codebase that knows about
an ElevenLabs endpoint or request/response shape (ADR-003 provider
firewall) - everything else depends on `NarrationProvider` /
`SoundEffectProvider` in `providers/base.py`.

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
from app.providers.base import (
    NarrationRequest,
    NarrationResult,
    SoundEffectRequest,
    SoundEffectResult,
)

_API_BASE_URL = "https://api.elevenlabs.io"
# A scene's narration is a handful of sentences; RV-Q10 may batch a
# contiguous run up to the model character cap (~5 min of audio on
# eleven_v3). 60s was enough per-scene and too tight for a batch.
_REQUEST_TIMEOUT_S = 300.0

# Per-request character caps. RV-Q10 packs contiguous scenes until this
# many characters; a single scene that is itself over the cap is still
# sent as one request, same as the pre-batch path. Unknown models use
# the conservative v3 cap.
#
# These are the PUBLISHED caps
# (https://elevenlabs.io/docs/overview/models, checked 2026-08-29)
# EXCEPT eleven_v3, which is deliberately below its published 5000 -
# do not "correct" it back by re-reading the docs.
#
# Measured 2026-09-08, project 3ad7d0ca ("plato uncovered", 29 Hindi
# scenes): a 4,679-character eleven_v3 request came back with audio that
# simply stopped ~4,496 characters in, twice, under two different voices
# (3AMU7jXQ and wlnkE6bN). Both times the last scene's final 183-184
# characters were pinned to the instant the audio ended - a silent
# truncation, since /with-timestamps still returns every character it
# was asked about. The two runs' audio differed by 17 seconds (352s vs
# 369s) but cut at the SAME character position, which is what rules out
# an audio-duration ceiling and points at a text-length one. ElevenLabs'
# own guidance for v3 is <=3000, so that is what this uses: at 3000 a
# 4,679-character film becomes two requests of 2,909 + 1,769, both with
# ~1,600 characters of headroom under the observed cliff.
#
# Cost is unaffected (billing is per character, not per request) and so
# is every cached row: the cap is not part of
# `compute_narration_content_hash`, so lowering it re-synthesises
# nothing. What it does cost is one extra voice seam per extra batch -
# the very discontinuity RV-Q10 exists to remove - so do not lower it
# further without a reason. `reject_truncated_alignment` is the backstop
# if the cliff ever moves (it may well be language-dependent: Devanagari
# is multi-byte and the model may not be counting Python `len`).
_TTS_CHAR_LIMIT_BY_MODEL = {
    "eleven_v3": 3000,
    "eleven_multilingual_v2": 10000,
    "eleven_multilingual_v1": 10000,
    "eleven_flash_v2_5": 40000,
    "eleven_flash_v2": 30000,
    "eleven_turbo_v2_5": 40000,
    "eleven_turbo_v2": 30000,
}
_TTS_CHAR_LIMIT_DEFAULT = 3000


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


def tts_request_character_limit(model: str) -> int:
    """Per-request character cap for `model`. Used by RV-Q10 batching."""
    return _TTS_CHAR_LIMIT_BY_MODEL.get(model, _TTS_CHAR_LIMIT_DEFAULT)


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


# --- Sound generation (long_form_direction.md A8, 2026-09-01) -------------
#
# `POST /v1/sound-generation`, verified against ElevenLabs' own docs (not
# memory) in the A8 gate (P-LF-A8-GEN-GATE, docs/plans/
# long_form_direction.md §7): `text` (required), `duration_seconds`
# (optional, 0.1-30s, auto-determined if omitted), `output_format` as a
# query param (same convention as the TTS endpoint above). No seed is
# documented for this endpoint - I5 for generated SFX comes entirely from
# the mandatory prompt-hash cache below, never from a generation input,
# exactly the same shape `resolve_assets.py::generation_prompt_hash`
# already uses for images/clips. Billed 40 credits/second when
# `duration_seconds` is specified (not character-based like narration).
_SOUND_GENERATION_DURATION_MIN_S = 0.1
_SOUND_GENERATION_DURATION_MAX_S = 30.0


def compute_sfx_generation_hash(*, text: str, model: str, duration_seconds: float) -> str:
    """The cache key for one diegetic-SFX generation request - mirrors
    `resolve_assets.py::generation_prompt_hash` and
    `compute_narration_content_hash` above exactly: hash the REQUEST
    (cue text + model + duration), look up, reuse or generate-and-store.
    This is the ONLY thing holding I5 for generated SFX, since the
    provider accepts no seed (§3 A8's own build note) - so unlike
    `generation_prompt_hash`, this is not optional plumbing, it is the
    entire determinism guarantee.

    `duration_seconds` is rounded to milliseconds before hashing so float
    reprs cannot fork the cache key for the same effective request."""
    digest_input = f"{text}|{model}|{round(duration_seconds, 3)}"
    return hashlib.sha256(digest_input.encode()).hexdigest()


class ElevenLabsSoundEffectProvider:
    """`SoundEffectProvider` for `/v1/sound-generation` (A8). Synchronous,
    single-call, no polling - unlike video generation, ElevenLabs resolves
    a sound-generation request in one response. Shares this module's auth
    convention (`xi-api-key` header) and error-handling shape with
    `ElevenLabsNarrationProvider.synthesize` above (401/403 permanent, 402
    permanent with the same top-up message, 429/5xx transient, every
    other 4xx permanent) rather than duplicating a second interpretation
    of the same status codes."""

    name = "elevenlabs"

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    async def generate(self, request: SoundEffectRequest) -> SoundEffectResult:
        if not settings.elevenlabs_api_key:
            raise PermanentError("ELEVENLABS_API_KEY is not configured")

        duration = min(
            max(request.duration_seconds, _SOUND_GENERATION_DURATION_MIN_S),
            _SOUND_GENERATION_DURATION_MAX_S,
        )
        url = f"{_API_BASE_URL}/v1/sound-generation"
        params = {"output_format": settings.elevenlabs_output_format}
        payload = {"text": request.text, "duration_seconds": duration}

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
                content_type = response.headers.get("content-type", "")
                # The documented response is a raw audio file
                # (elevenlabs.io/docs/api-reference/text-to-sound-effects).
                # A prior probe of this same endpoint (P-LF-A8-GEN-GATE)
                # recorded a JSON body carrying only base64 audio, the same
                # shape as the TTS endpoint above - ambiguous enough
                # (scoped API key, no second read) that this branches on
                # the response's own declared content type rather than
                # assuming either shape and crashing on the other.
                if content_type.startswith("audio/"):
                    content = response.content
                else:
                    data = response.json()
                    content = base64.b64decode(data["audio_base64"])
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise TransientError(f"elevenlabs sound generation timed out or errored: {exc}") from exc
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
            if status == 429 or status >= 500:
                raise TransientError(f"elevenlabs sound generation returned {status}") from exc
            raise PermanentError(f"elevenlabs sound generation failed: {exc}") from exc
        except (KeyError, TypeError, ValueError) as exc:
            raise PermanentError(
                f"elevenlabs sound-generation response missing valid audio: {exc}"
            ) from exc

        return SoundEffectResult(content=content, content_type="audio/mpeg")
