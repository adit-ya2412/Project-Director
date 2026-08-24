"""Hinglish code-switch probe (ad hoc, not tied to a plan doc section).

The production narration path (`ElevenLabsNarrationProvider.synthesize`,
`app/providers/elevenlabs.py`) sends raw Hindi/English code-mixed scene
text to `eleven_multilingual_v2` with no `voice_settings` beyond `speed`.
Reports of the voiceover "breaking" at Hindi<->English script switches
prompted this probe. `language_code` is documented as unsupported on
multilingual_v2, so the only in-model levers worth testing cheaply are
`voice_settings.stability`/`similarity_boost`, and whether `eleven_v3`
(a newer, more-multilingual model) is even accepted on the
`/with-timestamps` endpoint this codebase depends on for caption
alignment - that is genuinely undocumented and worth confirming live
before considering a model switch.

This makes NO decision and changes NO production code. It fires a
handful of real, cheap calls using an actual code-switched line from a
real script, saves each result as an mp3 under tmp/, and prints a JSON
summary - the same shape as `r8_speed_probe.py`. Listen to the files
and compare; that judgment can't be made programmatically.

Tiny real spend: one short Hindi/English sentence, 4 calls, ~200
characters total per call. Never prints the API key or voice id.

    .venv/Scripts/python.exe backend/scripts/hinglish_voice_probe.py
"""

from __future__ import annotations

import asyncio
import base64
import json
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
_REPO = _BACKEND.parent
sys.path.insert(0, str(_BACKEND))

import httpx  # noqa: E402

from app.core.config import settings  # noqa: E402

_API = "https://api.elevenlabs.io"
# Real line from the reported script - the switch at "Yamaha piano" /
# "lethal superbikes" is exactly the kind of mid-sentence Devanagari<->
# Latin boundary that reportedly breaks.
_TEXT = "Yamaha piano भी बनाती है। और lethal superbikes भी। लेकिन एक music company racing track पर कैसे पहुंची?"
_OUT = _REPO / "tmp" / "hinglish-voice-probe"


async def _call(client: httpx.AsyncClient, *, label: str, payload: dict) -> dict:
    voice_id = settings.elevenlabs_voice_id
    url = f"{_API}/v1/text-to-speech/{voice_id}/with-timestamps"
    params = {"output_format": settings.elevenlabs_output_format}
    try:
        response = await client.post(
            url,
            params=params,
            json=payload,
            headers={"xi-api-key": settings.elevenlabs_api_key},
        )
        status = response.status_code
        body_text = response.text
    except httpx.HTTPError as exc:
        return {
            "label": label,
            "ok": False,
            "status": None,
            "error": f"{type(exc).__name__}: {exc}",
        }

    record: dict = {
        "label": label,
        "ok": 200 <= status < 300,
        "status": status,
        "payload_keys": sorted(payload.keys()),
        "model_id": payload.get("model_id"),
        "voice_settings": payload.get("voice_settings"),
        "language_code": payload.get("language_code"),
        "chars": len(_TEXT),
    }
    if status >= 400:
        record["error_body"] = body_text[:800]
        return record

    data = response.json()
    alignment = data.get("alignment") or {}
    audio_b64 = data.get("audio_base64") or ""
    if audio_b64:
        _OUT.mkdir(parents=True, exist_ok=True)
        path = _OUT / f"{label}.mp3"
        path.write_bytes(base64.b64decode(audio_b64))
        record["saved"] = str(path.relative_to(_REPO))
    record.update(
        {
            "has_audio": bool(audio_b64),
            "has_alignment": bool(alignment),
            "alignment_chars": len(alignment.get("characters") or []),
        }
    )
    return record


async def main() -> int:
    print("key_configured:", bool(settings.elevenlabs_api_key))
    print("voice_configured:", bool(settings.elevenlabs_voice_id))
    print("production_model:", settings.elevenlabs_model)
    print("text:", _TEXT)
    if not settings.elevenlabs_api_key or not settings.elevenlabs_voice_id:
        print("ABORT: ELEVENLABS_API_KEY or ELEVENLABS_VOICE_ID missing")
        return 2

    cases = [
        # 1. Exactly what production sends today - the baseline to judge
        #    every other case against.
        (
            "baseline_multilingual_v2",
            {"text": _TEXT, "model_id": "eleven_multilingual_v2"},
        ),
        # 2. Higher stability: ElevenLabs docs say higher stability trades
        #    expressiveness for steadiness - candidate for smoothing over
        #    script-switch artifacts.
        (
            "multilingual_v2_stability_high",
            {
                "text": _TEXT,
                "model_id": "eleven_multilingual_v2",
                "voice_settings": {"stability": 0.75, "similarity_boost": 0.8},
            },
        ),
        # 3. Undocumented for this endpoint: does eleven_v3 even get
        #    accepted on /with-timestamps? If it 4xxs, the model-switch
        #    path is dead on arrival regardless of quality.
        (
            "eleven_v3_default",
            {"text": _TEXT, "model_id": "eleven_v3"},
        ),
        # 4. If v3 is accepted, also check whether it honours a language
        #    hint (docs say unsupported models silently ignore it rather
        #    than erroring, so this can't make things worse).
        (
            "eleven_v3_language_hi",
            {"text": _TEXT, "model_id": "eleven_v3", "language_code": "hi"},
        ),
    ]

    results = []
    async with httpx.AsyncClient(timeout=60.0) as client:
        for label, payload in cases:
            print(f"calling {label}...")
            record = await _call(client, label=label, payload=payload)
            results.append(record)
            print(json.dumps({k: v for k, v in record.items() if k != "error_body"}, indent=2))
            if record.get("error_body"):
                print("error_body:", record["error_body"])

    _OUT.mkdir(parents=True, exist_ok=True)
    (_OUT / "results.json").write_text(json.dumps({"results": results}, indent=2))
    print(f"\nsaved audio + results.json under {_OUT.relative_to(_REPO)}")
    print("listen and compare - this script makes no decision")
    return 0 if any(r["ok"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
