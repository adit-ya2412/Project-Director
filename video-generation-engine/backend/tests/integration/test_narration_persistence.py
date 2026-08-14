"""NarrationRepository + ElevenLabsNarrationProvider, wired together the
way a future workflow step will (M8 step 1 scope: no such step exists
yet - see the implementation guide, Phase M8 build order). Proves the
persistence half of the cache discipline: identical
text+voice_id+model+output_format must resolve from the `narration` table
on a second pass without a second provider call, exactly the same
discipline `generated_clip.prompt_hash` already enforces for generated
media (ladder rung 0).

Runs against the real Postgres test DB (see `tests/conftest.py`), with a
`MockTransport` standing in for ElevenLabs - no real network, no real
money spent.
"""

import base64
import os
import uuid as uuid_module

import httpx
import pytest_asyncio

from app.core.config import settings
from app.db.session import async_session_factory
from app.providers.base import NarrationRequest
from app.providers.elevenlabs import ElevenLabsNarrationProvider, compute_narration_content_hash
from app.repositories.narration_repository import NarrationRepository
from app.repositories.project_repository import PostgresProjectRepository

_SCENE_TEXT = "Germany possessed abundant coal, but lacked domestic oil reserves."
_ALIGNMENT = {
    "characters": list(_SCENE_TEXT),
    "character_start_times_seconds": [i * 0.05 for i in range(len(_SCENE_TEXT))],
    "character_end_times_seconds": [(i + 1) * 0.05 for i in range(len(_SCENE_TEXT))],
}


@pytest_asyncio.fixture
async def project_id() -> str:
    async with async_session_factory() as session:
        repo = PostgresProjectRepository(session)
        project = await repo.create("narration-persistence-test")
        return project.id


def _counting_transport(call_count: list[int]) -> httpx.MockTransport:
    async def handler(request: httpx.Request) -> httpx.Response:
        call_count[0] += 1
        return httpx.Response(
            200,
            json={
                "audio_base64": base64.b64encode(b"mp3-bytes-for-scene").decode("ascii"),
                "alignment": _ALIGNMENT,
                "normalized_alignment": {
                    "characters": [],
                    "character_start_times_seconds": [],
                    "character_end_times_seconds": [],
                },
            },
        )

    return httpx.MockTransport(handler)


async def _synthesize_and_persist_if_missing(
    *,
    project_id: str,
    scene_id: str,
    request: NarrationRequest,
    provider: ElevenLabsNarrationProvider,
) -> None:
    """Stands in for the (not-yet-built) workflow step: check the cache
    before paying for a synthesis call, exactly per D3/ladder-rung-0
    discipline."""
    content_hash = compute_narration_content_hash(
        text=request.text,
        voice_id=request.voice_id,
        model=request.model,
        output_format=request.output_format,
    )
    async with async_session_factory() as session:
        repo = NarrationRepository(session)
        if await repo.get_by_content_hash(content_hash) is not None:
            return  # cache hit - never call the provider

        result = await provider.synthesize(request)

        project_dir = settings.storage_root / project_id / "narration"
        project_dir.mkdir(parents=True, exist_ok=True)
        path = project_dir / f"{content_hash}.mp3"
        path.write_bytes(result.content)

        await repo.insert(
            project_id=uuid_module.UUID(project_id),
            scene_id=scene_id,
            provider=provider.name,
            voice_id=request.voice_id,
            model_id=request.model,
            output_format=request.output_format,
            text=request.text,
            content_hash=content_hash,
            local_path=str(path),
            alignment=result.alignment,
            character_count=result.character_count,
            cost_cents=round(result.character_count * settings.elevenlabs_cost_cents_per_character),
        )
        await session.commit()


async def test_second_identical_request_never_calls_the_provider(project_id, monkeypatch):
    monkeypatch.setattr(settings, "elevenlabs_api_key", "fake-key")
    call_count = [0]
    provider = ElevenLabsNarrationProvider(transport=_counting_transport(call_count))
    request = NarrationRequest(
        text=_SCENE_TEXT,
        voice_id="voice_abc",
        model="eleven_multilingual_v2",
        output_format="mp3_44100_128",
        scene_id="sc_01",
    )

    await _synthesize_and_persist_if_missing(
        project_id=project_id, scene_id="sc_01", request=request, provider=provider
    )
    assert call_count[0] == 1

    await _synthesize_and_persist_if_missing(
        project_id=project_id, scene_id="sc_01", request=request, provider=provider
    )
    assert call_count[0] == 1  # cache hit - no second network call


async def test_row_persists_alignment_voice_model_and_character_count(project_id, monkeypatch):
    monkeypatch.setattr(settings, "elevenlabs_api_key", "fake-key")
    provider = ElevenLabsNarrationProvider(transport=_counting_transport([0]))
    request = NarrationRequest(
        text=_SCENE_TEXT,
        voice_id="voice_abc",
        model="eleven_multilingual_v2",
        output_format="mp3_44100_128",
        scene_id="sc_02",
    )

    await _synthesize_and_persist_if_missing(
        project_id=project_id, scene_id="sc_02", request=request, provider=provider
    )

    content_hash = compute_narration_content_hash(
        text=request.text,
        voice_id=request.voice_id,
        model=request.model,
        output_format=request.output_format,
    )
    async with async_session_factory() as session:
        repo = NarrationRepository(session)
        row = await repo.get_by_content_hash(content_hash)

    assert row is not None
    assert row.scene_id == "sc_02"
    assert row.voice_id == "voice_abc"
    assert row.model_id == "eleven_multilingual_v2"
    assert row.output_format == "mp3_44100_128"
    assert row.character_count == len(_SCENE_TEXT)
    assert row.alignment["characters"] == _ALIGNMENT["characters"]
    assert row.cost_cents == round(len(_SCENE_TEXT) * settings.elevenlabs_cost_cents_per_character)
    # D3: content-hash filename, under {project}/narration/.
    assert row.local_path.endswith(os.path.join("narration", f"{content_hash}.mp3"))


async def test_different_voice_id_is_a_cache_miss_and_calls_the_provider_again(
    project_id, monkeypatch
):
    monkeypatch.setattr(settings, "elevenlabs_api_key", "fake-key")
    call_count = [0]
    provider = ElevenLabsNarrationProvider(transport=_counting_transport(call_count))

    request_a = NarrationRequest(
        text=_SCENE_TEXT,
        voice_id="voice_a",
        model="eleven_multilingual_v2",
        output_format="mp3_44100_128",
        scene_id="sc_03",
    )
    request_b = NarrationRequest(
        text=_SCENE_TEXT,
        voice_id="voice_b",  # only the voice differs
        model="eleven_multilingual_v2",
        output_format="mp3_44100_128",
        scene_id="sc_03",
    )

    await _synthesize_and_persist_if_missing(
        project_id=project_id, scene_id="sc_03", request=request_a, provider=provider
    )
    await _synthesize_and_persist_if_missing(
        project_id=project_id, scene_id="sc_03", request=request_b, provider=provider
    )
    assert call_count[0] == 2  # different voice_id -> different hash -> not a cache hit
