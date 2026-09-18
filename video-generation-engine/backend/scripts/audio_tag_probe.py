"""Probe: do eleven_v3 audio tags survive into the /with-timestamps alignment?

Phase 0 of docs/plans/narration_tone_tags.md.

The question this answers: narration_batch.split_batched_alignment() rebuilds
`expected = join_batch_text(members)` and compares it against the characters
ElevenLabs returns (narration_batch.py:252-254). If audio tags are consumed as
directives and omitted from the returned character stream, that equality check
fails and per-scene splitting breaks.

Usage:
    .venv/Scripts/python.exe backend/scripts/audio_tag_probe.py phase0
    .venv/Scripts/python.exe backend/scripts/audio_tag_probe.py phase1

Writes audio + raw alignment JSON to tmp/audio_tag_probe/. Prints ASCII only --
never the Devanagari source -- so a cp1252 console cannot kill the run.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))

from app.core.config import settings  # noqa: E402
from app.providers.base import NarrationRequest  # noqa: E402
from app.providers.elevenlabs import ElevenLabsNarrationProvider  # noqa: E402

# Matches NARRATION_BATCH_JOINER at backend/app/timeline/narration_batch.py:53
JOINER = "\n"

OUT = Path(__file__).resolve().parents[2] / "tmp" / "audio_tag_probe"

# Two short scenes, as the batcher would join them.
SCENE_A1 = "2001 का साल।"
SCENE_A2 = "जब पूरा भारत, geared scooters चलाता था।"

CLEAN_PAIR = JOINER.join([SCENE_A1, SCENE_A2])
TAGGED_PAIR = JOINER.join([f"[excited] {SCENE_A1}", f"[curious] {SCENE_A2}"])

ACTIVA_CLEAN = """2001 का साल।
जब पूरा भारत, geared scooters चलाता था।
तभी, Honda ने, एक ऐसी scooter उतारी, जिसमें gear ही नहीं था।
नाम था, Activa।
Reliable, आसान, और बेहतरीन mileage।
जल्द ही, Activa सिर्फ एक product नहीं रहा।
वो, scooter का ही, दूसरा नाम बन गया।
एक वक़्त, Honda का market share, 57 percent तक पहुंच गया था।
हर घर में, एक Activa होना, आम बात थी।
लेकिन इसी बीच, TVS ने, चुपचाप, अपनी चालें चलनी शुरू कीं।
Activa को टक्कर देने के लिए, आई Jupiter.
Young crowd के लिए, आया NTorq.
और फिर, आया सबसे बड़ा दांव।
Electric scooters, iQube.
Honda से बहुत पहले, TVS इस race में उतर गई।
आज, Honda का हिस्सा, गिरकर 35 percent तक आ चुका है।
वहीं, TVS का हिस्सा, लगभग दोगुना होकर, 28 percent के पार पहुंच गया है।
Activa, आज भी, नंबर 1 है।
लेकिन जो राज, कभी अजेय लगता था।
अब, हर साल, थोड़ा कमज़ोर होता जा रहा है।
तो क्या, Activa का दबदबा, आख़िरकार खत्म होने वाला है?
Comment करके बताइए।"""

ACTIVA_TAGGED = """[excited] 2001 का साल।
जब पूरा भारत, geared scooters चलाता था।
तभी, Honda ने, एक ऐसी scooter उतारी, जिसमें gear ही नहीं था।
नाम था, Activa।
[curious] Reliable, आसान, और बेहतरीन mileage।
जल्द ही, Activa सिर्फ एक product नहीं रहा।
वो, scooter का ही, दूसरा नाम बन गया।
एक वक़्त, Honda का market share, 57 percent तक पहुंच गया था।
हर घर में, एक Activa होना, आम बात थी।
[whispers] लेकिन इसी बीच, TVS ने, चुपचाप, अपनी चालें चलनी शुरू कीं।
[curious] Activa को टक्कर देने के लिए, आई Jupiter.
Young crowd के लिए, आया NTorq.
और फिर, आया सबसे बड़ा दांव।
Electric scooters, iQube.
Honda से बहुत पहले, TVS इस race में उतर गई।
[serious] आज, Honda का हिस्सा, गिरकर 35 percent तक आ चुका है।
वहीं, TVS का हिस्सा, लगभग दोगुना होकर, 28 percent के पार पहुंच गया है।
Activa, आज भी, नंबर 1 है।
लेकिन जो राज, कभी अजेय लगता था।
अब, हर साल, थोड़ा कमज़ोर होता जा रहा है।
[curious] तो क्या, Activa का दबदबा, आख़िरकार खत्म होने वाला है?
Comment करके बताइए।"""


# Phase 1c-A: what per-scene tone expansion actually sends. The gate design writes an
# explicit tone to every scene, so a clubbed run of 5 scenes emits its tag 5 times
# rather than once holding across them. Does that over-emphasize?
ACTIVA_EXPANDED = """[excited] 2001 का साल।
[excited] जब पूरा भारत, geared scooters चलाता था।
[excited] तभी, Honda ने, एक ऐसी scooter उतारी, जिसमें gear ही नहीं था।
[excited] नाम था, Activa।
[curious] Reliable, आसान, और बेहतरीन mileage।
[curious] जल्द ही, Activa सिर्फ एक product नहीं रहा।
[curious] वो, scooter का ही, दूसरा नाम बन गया।
[curious] एक वक़्त, Honda का market share, 57 percent तक पहुंच गया था।
[curious] हर घर में, एक Activa होना, आम बात थी।
[whispers] लेकिन इसी बीच, TVS ने, चुपचाप, अपनी चालें चलनी शुरू कीं।
[curious] Activa को टक्कर देने के लिए, आई Jupiter.
[curious] Young crowd के लिए, आया NTorq.
[curious] और फिर, आया सबसे बड़ा दांव।
[curious] Electric scooters, iQube.
[curious] Honda से बहुत पहले, TVS इस race में उतर गई।
[serious] आज, Honda का हिस्सा, गिरकर 35 percent तक आ चुका है।
[serious] वहीं, TVS का हिस्सा, लगभग दोगुना होकर, 28 percent के पार पहुंच गया है।
[serious] Activa, आज भी, नंबर 1 है।
[serious] लेकिन जो राज, कभी अजेय लगता था।
[serious] अब, हर साल, थोड़ा कमज़ोर होता जा रहा है।
[curious] तो क्या, Activa का दबदबा, आख़िरकार खत्म होने वाला है?
[curious] Comment करके बताइए।"""

# Phase 1c-B: which tags actually do anything on Hindi? [dramatic] is deliberately
# not a documented v3 tag -- included to see what an unsupported tag does.
VOCAB_LINE = "तो क्या, Activa का दबदबा, आख़िरकार खत्म होने वाला है?"
VOCAB_TAGS = ["", "[excited]", "[curious]", "[whispers]", "[serious]", "[sarcastic]", "[dramatic]"]


def _chars(alignment: dict) -> list[str]:
    """Pull the character array out, tolerating either alignment shape."""
    if not isinstance(alignment, dict):
        return []
    if isinstance(alignment.get("characters"), list):
        return alignment["characters"]
    nested = alignment.get("normalized_alignment")
    if isinstance(nested, dict) and isinstance(nested.get("characters"), list):
        return nested["characters"]
    return []


def _ascii(text: str, limit: int = 120) -> str:
    """Escape to pure ASCII so any console can print it."""
    return text[:limit].encode("unicode_escape").decode("ascii")


async def _run(
    provider,
    label: str,
    text: str,
    language_code: str | None,
    voice_id: str | None = None,
) -> dict:
    request = NarrationRequest(
        text=text,
        voice_id=voice_id or settings.elevenlabs_voice_id,
        model=settings.elevenlabs_model,
        output_format=settings.elevenlabs_output_format,
        scene_id=f"probe-{label}",
        language_code=language_code,
    )
    result = await provider.synthesize(request)

    chars = _chars(result.alignment)
    returned = "".join(chars)

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{label}.mp3").write_bytes(result.content)
    (OUT / f"{label}.alignment.json").write_text(
        json.dumps(result.alignment, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (OUT / f"{label}.sent.txt").write_text(text, encoding="utf-8")
    (OUT / f"{label}.returned.txt").write_text(returned, encoding="utf-8")

    match = returned == text
    first_diff = -1
    if not match:
        for i in range(min(len(returned), len(text))):
            if returned[i] != text[i]:
                first_diff = i
                break
        else:
            first_diff = min(len(returned), len(text))

    print(f"\n--- {label} ---")
    print(f"  audio bytes         : {len(result.content)}")
    print(f"  chars sent          : {len(text)}")
    print(f"  chars returned      : {len(returned)}")
    print(f"  character_count     : {result.character_count}")
    print(f"  EXACT MATCH         : {match}")
    if not match:
        print(f"  first divergence at : {first_diff}")
        print(f"    sent     [{first_diff}:] {_ascii(text[first_diff:], 60)}")
        print(f"    returned [{first_diff}:] {_ascii(returned[first_diff:], 60)}")
    for tag in ("[excited]", "[curious]", "[whispers]", "[serious]"):
        if tag in text:
            print(f"  tag {tag:<11} in returned : {tag in returned}")
    print(f"  newline joiner survived : {returned.count(JOINER)} of {text.count(JOINER)}")

    return {
        "label": label,
        "match": match,
        "sent_len": len(text),
        "returned_len": len(returned),
        "tags_echoed": {t: (t in returned) for t in ("[excited]", "[curious]", "[whispers]", "[serious]") if t in text},
        "newlines_sent": text.count(JOINER),
        "newlines_returned": returned.count(JOINER),
    }


async def main() -> int:
    phase = sys.argv[1] if len(sys.argv) > 1 else "phase0"

    if not settings.elevenlabs_api_key:
        print("ERROR: ELEVENLABS_API_KEY is not set in the environment.")
        return 2
    if not settings.elevenlabs_voice_id:
        print("ERROR: ELEVENLABS_VOICE_ID is not set; the probe needs an explicit voice.")
        return 2

    print(f"model         : {settings.elevenlabs_model}")
    print(f"output_format : {settings.elevenlabs_output_format}")
    print(f"voice_id      : ...{settings.elevenlabs_voice_id[-4:]}")
    print(f"language_code : {settings.elevenlabs_language_code!r}")
    print(f"phase         : {phase}")

    provider = ElevenLabsNarrationProvider()
    summary = []

    if phase in ("phase0", "all"):
        summary.append(await _run(provider, "a_clean_pair", CLEAN_PAIR, settings.elevenlabs_language_code))
        summary.append(await _run(provider, "b_tagged_pair", TAGGED_PAIR, settings.elevenlabs_language_code))

        # Does v3 reject language_code? Only worth one extra call if it is set.
        if settings.elevenlabs_language_code:
            try:
                await _run(provider, "c_no_langcode", TAGGED_PAIR, None)
            except Exception as exc:  # noqa: BLE001 - probe, report and continue
                print(f"\n--- c_no_langcode --- FAILED: {type(exc).__name__}: {exc}")

    if phase in ("phase1", "all"):
        summary.append(await _run(provider, "activa_clean", ACTIVA_CLEAN, settings.elevenlabs_language_code))
        summary.append(await _run(provider, "activa_tagged", ACTIVA_TAGGED, settings.elevenlabs_language_code))

    if phase == "phase1c":
        summary.append(
            await _run(provider, "activa_expanded", ACTIVA_EXPANDED, settings.elevenlabs_language_code)
        )
        for tag in VOCAB_TAGS:
            label = "vocab_baseline" if not tag else f"vocab_{tag.strip('[]')}"
            text = f"{tag} {VOCAB_LINE}".strip()
            summary.append(await _run(provider, label, text, settings.elevenlabs_language_code))

    if phase == "voices":
        # Same tagged script, different voices, so the comparison is tone-for-tone.
        voice_ids = sys.argv[2:]
        if not voice_ids:
            print("ERROR: pass one or more voice ids after 'voices'.")
            return 2
        for vid in voice_ids:
            summary.append(
                await _run(
                    provider,
                    f"activa_tagged_voice_{vid[-4:]}",
                    ACTIVA_TAGGED,
                    settings.elevenlabs_language_code,
                    voice_id=vid,
                )
            )

    (OUT / f"summary_{phase}.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("\n=== VERDICT ===")
    for row in summary:
        print(f"  {row['label']:<16} exact_match={row['match']}  tags_echoed={row['tags_echoed']}")
    print(f"\nartifacts: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
