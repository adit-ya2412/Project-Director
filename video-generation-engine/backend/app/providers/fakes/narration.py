"""Fake narration provider (M8, D1 DRY_RUN path).

Fabricates a uniform-rate, gap-free character alignment for whatever text
it's given, instead of calling ElevenLabs — deterministic and free, so
DRY_RUN still exercises `narration_fit.py`'s reconciliation against a real
(if fake) alignment end to end, rather than skipping it. This is not
throwaway scaffolding: it stays forever as the DRY_RUN implementation and
the fast, free unit-test double (implementation guide section 4.1).
"""

from app.providers.base import NarrationRequest, NarrationResult
from app.providers.elevenlabs import canonical_narration_speed

# A plausible, deterministic reading rate. The exact value never matters —
# DRY_RUN doesn't have to sound right, only to produce a fully-populated,
# internally consistent (gap-free) alignment so reconciliation has real
# numbers to work with.
_CHARACTERS_PER_SECOND = 15.0


class FakeNarrationProvider:
    name = "fake_narration"

    async def synthesize(self, request: NarrationRequest) -> NarrationResult:
        text = request.text
        # Honour speed so DRY_RUN retention_fast is actually faster, not
        # a fast-cut picture over documentary-paced fake speech (the
        # mismatch parent plan §2.5 warned about). Through
        # `canonical_narration_speed`, not the raw field (§15.6): the
        # real provider CLAMPS to the live-checked 0.7-1.2 band, so a
        # fake that honoured an out-of-band value would make DRY_RUN
        # disagree with production about how long a scene takes - the
        # one thing this provider exists to get right.
        rate = _CHARACTERS_PER_SECOND * canonical_narration_speed(request.speed)
        alignment = {
            "characters": list(text),
            "character_start_times_seconds": [i / rate for i in range(len(text))],
            "character_end_times_seconds": [(i + 1) / rate for i in range(len(text))],
        }
        content = f"fake-narration-audio:{request.scene_id}:{text}".encode()
        return NarrationResult(content=content, alignment=alignment, character_count=len(text))
