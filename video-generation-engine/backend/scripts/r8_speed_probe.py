"""R8 live schema/behaviour check (parent plan §2.1 / §13.8 / §14.2).

Confirms that POST /v1/text-to-speech/{voice_id}/with-timestamps on the
configured eleven_multilingual_v2 model accepts voice_settings.speed,
that 1.2 is in range, that duration actually scales, and that alignment
timestamps scale with it (D2 captions depend on those).

Tiny real spend: one short English sentence, three calls
(no voice_settings / speed=1.0 / speed=1.2). ~165 characters total.

    .venv/Scripts/python.exe backend/scripts/r8_speed_probe.py

Never prints the API key or voice id.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
_REPO = _BACKEND.parent
sys.path.insert(0, str(_BACKEND))

import httpx  # noqa: E402

from app.core.config import settings  # noqa: E402

_API = "https://api.elevenlabs.io"
_TEXT = "Germany possessed abundant coal, but lacked domestic oil."
_OUT = _REPO / "tmp" / "r8-speed-probe"


def _duration_s(alignment: dict | None) -> float | None:
    if not alignment:
        return None
    ends = alignment.get("character_end_times_seconds") or []
    return float(ends[-1]) if ends else None


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
        "voice_settings": payload.get("voice_settings"),
        "chars": len(_TEXT),
    }
    if status >= 400:
        record["error_body"] = body_text[:800]
        return record

    data = response.json()
    alignment = data.get("alignment") or {}
    audio_b64 = data.get("audio_base64") or ""
    audio_bytes = len(audio_b64) * 3 // 4 if audio_b64 else 0
    record.update(
        {
            "has_audio": bool(audio_b64),
            "audio_approx_bytes": audio_bytes,
            "has_alignment": bool(alignment),
            "alignment_chars": len(alignment.get("characters") or []),
            "duration_s": _duration_s(alignment),
            "response_keys": sorted(data.keys()),
        }
    )
    if audio_b64:
        import base64

        _OUT.mkdir(parents=True, exist_ok=True)
        path = _OUT / f"{label}.mp3"
        path.write_bytes(base64.b64decode(audio_b64))
        record["saved"] = str(path.relative_to(_REPO))
    return record


async def main() -> int:
    print("key_configured:", bool(settings.elevenlabs_api_key))
    print("voice_configured:", bool(settings.elevenlabs_voice_id))
    print("model:", settings.elevenlabs_model)
    print("output_format:", settings.elevenlabs_output_format)
    print("text_chars:", len(_TEXT))
    if not settings.elevenlabs_api_key or not settings.elevenlabs_voice_id:
        print("ABORT: ELEVENLABS_API_KEY or ELEVENLABS_VOICE_ID missing")
        return 2

    cases = [
        (
            "no_voice_settings",
            {"text": _TEXT, "model_id": settings.elevenlabs_model},
        ),
        (
            "speed_1_0",
            {
                "text": _TEXT,
                "model_id": settings.elevenlabs_model,
                "voice_settings": {"speed": 1.0},
            },
        ),
        (
            "speed_1_2",
            {
                "text": _TEXT,
                "model_id": settings.elevenlabs_model,
                "voice_settings": {"speed": 1.2},
            },
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

    durations = {r["label"]: r.get("duration_s") for r in results}
    d_none = durations.get("no_voice_settings")
    d_10 = durations.get("speed_1_0")
    d_12 = durations.get("speed_1_2")
    summary: dict = {"durations_s": durations}
    if d_none and d_10:
        summary["omit_vs_1_0_ratio"] = round(d_none / d_10, 4)
    if d_10 and d_12:
        summary["duration_1_0_over_1_2"] = round(d_10 / d_12, 4)
        summary["expected_ratio"] = 1.2
        summary["scaled"] = abs((d_10 / d_12) - 1.2) < 0.15
    print("SUMMARY")
    print(json.dumps(summary, indent=2))
    _OUT.mkdir(parents=True, exist_ok=True)
    (_OUT / "results.json").write_text(json.dumps({"results": results, "summary": summary}, indent=2))
    return 0 if all(r["ok"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
