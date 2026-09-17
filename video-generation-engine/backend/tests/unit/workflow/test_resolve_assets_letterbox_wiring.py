"""docs/plans/baked_in_letterbox.md §5.1/§5.3: the two `resolve_assets.py`
call sites for `strip_baked_in_letterbox`.

- `_prefetch_search_rungs` (§5.1): the crop must run on `fetched.content`
  BEFORE `hashlib.sha256(...)` is taken, not after - `fetched.content` is
  read in exactly two places (that hash, and the tuple appended right
  below it), so this is the one point that keeps ranking/dedup/insert all
  agreeing on a single hash for the CORRECTED bytes.
- `poll_video_job` (§5.3): no hash-ordering hazard (`prompt_hash` describes
  the request, never the output pixels) - a plain wrap before the write.

No real provider, no real fal.ai job - `strip_baked_in_letterbox` itself
is mocked throughout (already covered against real ffmpeg by
`tests/unit/assets/test_letterbox_crop.py`); these tests are about WIRING
and ORDERING, not detection.
"""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path
from types import SimpleNamespace

import app.workflow.steps.resolve_assets as resolve_assets_module
from app.core.config import settings
from app.providers.base import AssetBytes, AssetCandidate, AssetQuery
from app.schemas.timeline import AssetPlan, AssetStrategy, CreativeContext, PreferredMediaType, Shot
from app.workflow.steps.resolve_assets import ResolveAssetsStep

_RAW_VIDEO = b"raw-video-bytes"
_RAW_IMAGE = b"raw-image-bytes"


def _fake_strip(calls: list[bytes], marker: bytes = b"CROPPED"):
    async def fake_strip(content, *, ffmpeg_binary, ffprobe_binary):
        calls.append(content)
        return content + marker

    return fake_strip


class _FakeProvider:
    """Returns one fixed candidate/bytes pair - `media_kind` is the only
    thing that varies between tests."""

    name = "fake_provider"

    def __init__(self, *, media_kind: str, content: bytes):
        self._media_kind = media_kind
        self._content = content
        self.fetch_calls = 0

    async def search(self, query: AssetQuery) -> list[AssetCandidate]:
        return [
            AssetCandidate(
                source_id="c1",
                source_url="https://example.test/c1",
                title="castle",  # matches search_queries below for the relevance gate
                licence="cc0",
                media_kind=self._media_kind,
            )
        ]

    async def fetch(self, candidate: AssetCandidate) -> AssetBytes:
        self.fetch_calls += 1
        return AssetBytes(content=self._content, content_type="video/mp4", attribution="")


def _shot_with_plan(shot_id: str = "sh1") -> Shot:
    plan = AssetPlan(
        strategy=AssetStrategy.STOCK_SEARCH,
        search_queries=["castle"],
        preferred_type=PreferredMediaType.VIDEO,
        fallback_chain=[AssetStrategy.STOCK_SEARCH],
    )
    return Shot(id=shot_id, order=0, intent="explain", duration_s=3.0, asset_plan=plan)


async def _run_prefetch(step: ResolveAssetsStep, provider: _FakeProvider):
    shot = _shot_with_plan()
    return await step._prefetch_search_rungs(
        shot,
        search_providers={AssetStrategy.STOCK_SEARCH: provider},
        entity_provider=None,
        creative_context=CreativeContext(),
        db_lock=None,
    )


async def test_prefetch_crops_video_before_hashing(monkeypatch):
    calls: list[bytes] = []
    monkeypatch.setattr(settings, "letterbox_crop_enabled", True)
    monkeypatch.setattr(resolve_assets_module, "strip_baked_in_letterbox", _fake_strip(calls))

    step = ResolveAssetsStep(name="t", permitted_strategies=frozenset({AssetStrategy.STOCK_SEARCH}))
    provider = _FakeProvider(media_kind="video", content=_RAW_VIDEO)
    rungs = await _run_prefetch(step, provider)

    assert calls == [_RAW_VIDEO]  # crop ran on the RAW fetched bytes
    assert len(rungs) == 1
    (candidate, content_hash, content, _attribution) = rungs[0].entries[0]
    expected_content = _RAW_VIDEO + b"CROPPED"
    assert content == expected_content
    # The hash stored alongside the entry (later used for dedup, ranking,
    # and the eventual `asset_repo.insert`) must describe THESE bytes.
    assert content_hash == hashlib.sha256(expected_content).hexdigest()


async def test_prefetch_does_not_crop_an_image(monkeypatch):
    calls: list[bytes] = []
    monkeypatch.setattr(settings, "letterbox_crop_enabled", True)
    monkeypatch.setattr(resolve_assets_module, "strip_baked_in_letterbox", _fake_strip(calls))

    step = ResolveAssetsStep(name="t", permitted_strategies=frozenset({AssetStrategy.STOCK_SEARCH}))
    provider = _FakeProvider(media_kind="image", content=_RAW_IMAGE)
    rungs = await _run_prefetch(step, provider)

    assert calls == []
    (_candidate, content_hash, content, _attribution) = rungs[0].entries[0]
    assert content == _RAW_IMAGE
    assert content_hash == hashlib.sha256(_RAW_IMAGE).hexdigest()


async def test_prefetch_kill_switch_is_a_byte_identical_no_op(monkeypatch):
    calls: list[bytes] = []
    monkeypatch.setattr(settings, "letterbox_crop_enabled", False)
    monkeypatch.setattr(resolve_assets_module, "strip_baked_in_letterbox", _fake_strip(calls))

    step = ResolveAssetsStep(name="t", permitted_strategies=frozenset({AssetStrategy.STOCK_SEARCH}))
    provider = _FakeProvider(media_kind="video", content=_RAW_VIDEO)
    rungs = await _run_prefetch(step, provider)

    assert calls == []
    (_candidate, content_hash, content, _attribution) = rungs[0].entries[0]
    assert content == _RAW_VIDEO
    assert content_hash == hashlib.sha256(_RAW_VIDEO).hexdigest()


# --- poll_video_job (§5.3) -------------------------------------------------


class _FakeClipRepo:
    def __init__(self, in_flight):
        self._in_flight = in_flight
        self.completed: list[str] = []

    async def get_in_flight_for_shot(self, project_uuid, shot_id):
        return self._in_flight

    async def mark_completed(self, clip, *, local_path, duration_s, cost_cents):
        self.completed.append(local_path)


class _FakeVideoProvider:
    def __init__(self, content: bytes):
        self._content = content

    async def poll(self, job_id):
        return SimpleNamespace(state="completed", content=self._content, error=None)


async def _run_poll_video_job(tmp_path, *, content: bytes):
    (tmp_path / "clips").mkdir(parents=True, exist_ok=True)
    in_flight = SimpleNamespace(id="clip-1", job_id="job-1", prompt_hash="hash-1", cost_cents=10)
    binding = SimpleNamespace(clip_id=None, state="pending", rung=None, last_error=None)
    shot = SimpleNamespace(id="sh1", duration_s=3.0)
    clip_repo = _FakeClipRepo(in_flight)
    video_provider = _FakeVideoProvider(content)
    await resolve_assets_module.poll_video_job(
        shot,
        binding,
        project_uuid=uuid.uuid4(),
        project_dir=tmp_path,
        video_provider=video_provider,
        clip_repo=clip_repo,
    )
    return tmp_path / "clips" / "hash-1.mp4"


async def test_poll_video_job_crops_before_writing(monkeypatch, tmp_path):
    calls: list[bytes] = []
    monkeypatch.setattr(settings, "letterbox_crop_enabled", True)
    monkeypatch.setattr(resolve_assets_module, "strip_baked_in_letterbox", _fake_strip(calls))

    written_path = await _run_poll_video_job(tmp_path, content=_RAW_VIDEO)

    assert calls == [_RAW_VIDEO]
    assert written_path.read_bytes() == _RAW_VIDEO + b"CROPPED"


async def test_poll_video_job_kill_switch_is_a_byte_identical_no_op(monkeypatch, tmp_path):
    calls: list[bytes] = []
    monkeypatch.setattr(settings, "letterbox_crop_enabled", False)
    monkeypatch.setattr(resolve_assets_module, "strip_baked_in_letterbox", _fake_strip(calls))

    written_path = await _run_poll_video_job(tmp_path, content=_RAW_VIDEO)

    assert calls == []
    assert written_path.read_bytes() == _RAW_VIDEO
