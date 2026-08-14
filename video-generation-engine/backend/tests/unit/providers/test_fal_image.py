"""FalImageProvider tests - a fake FalQueueClient stands in for the real
fal.ai queue (no network), and httpx.MockTransport stands in for the
downloaded image bytes."""

import asyncio

import httpx
import pytest

from app.core.errors import PermanentError, TransientError
from app.providers.base import ImageRequest
from app.providers.fal_image import FalImageProvider


class _FakeQueueClient:
    def __init__(self, poll_sequence: list[tuple[str, dict | None, str | None]]) -> None:
        self._poll_sequence = list(poll_sequence)
        self.submit_calls: list[tuple[str, dict]] = []
        self.poll_calls = 0

    async def submit(self, model_id: str, arguments: dict) -> str:
        self.submit_calls.append((model_id, arguments))
        return "job-1"

    async def poll_once(self, model_id: str, job_id: str):
        self.poll_calls += 1
        return self._poll_sequence.pop(0)


def _download_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, content=b"fake-image-bytes", headers={"content-type": "image/jpeg"})


async def test_generate_submits_prompt_size_and_seed():
    queue = _FakeQueueClient(
        [("completed", {"images": [{"url": "http://fal.example/x.jpg"}]}, None)]
    )
    provider = FalImageProvider(queue, transport=httpx.MockTransport(_download_handler))

    await provider.generate(
        ImageRequest(prompt="a coal mine", width=1080, height=1920, shot_id="sh_01", seed=42)
    )

    model_id, arguments = queue.submit_calls[0]
    assert arguments["prompt"] == "a coal mine"
    assert arguments["image_size"] == {"width": 1080, "height": 1920}
    assert arguments["seed"] == 42


async def test_generate_returns_bytes_and_hosted_url():
    queue = _FakeQueueClient(
        [("completed", {"images": [{"url": "http://fal.example/x.jpg"}]}, None)]
    )
    provider = FalImageProvider(queue, transport=httpx.MockTransport(_download_handler))

    result = await provider.generate(
        ImageRequest(prompt="a coal mine", width=1080, height=1920, shot_id="sh_01")
    )

    assert result.content == b"fake-image-bytes"
    assert result.hosted_url == "http://fal.example/x.jpg"


async def test_generate_polls_until_completed():
    queue = _FakeQueueClient(
        [
            ("in_progress", None, None),
            ("in_progress", None, None),
            ("completed", {"images": [{"url": "http://fal.example/x.jpg"}]}, None),
        ]
    )
    provider = FalImageProvider(queue, transport=httpx.MockTransport(_download_handler))

    result = await provider.generate(
        ImageRequest(prompt="p", width=1080, height=1920, shot_id="sh_01")
    )

    assert queue.poll_calls == 3
    assert result.content == b"fake-image-bytes"


async def test_generate_raises_permanent_error_on_job_failure():
    queue = _FakeQueueClient([("failed", None, "content policy violation")])
    provider = FalImageProvider(queue, transport=httpx.MockTransport(_download_handler))

    with pytest.raises(PermanentError, match="content policy violation"):
        await provider.generate(ImageRequest(prompt="p", width=1080, height=1920, shot_id="sh_01"))


async def test_generate_times_out_as_transient_error(monkeypatch):
    original_sleep = asyncio.sleep
    monkeypatch.setattr(asyncio, "sleep", lambda _seconds: original_sleep(0))
    queue = _FakeQueueClient([("in_progress", None, None)] * 100)
    provider = FalImageProvider(queue, transport=httpx.MockTransport(_download_handler))

    with pytest.raises(TransientError, match="did not complete"):
        await provider.generate(ImageRequest(prompt="p", width=1080, height=1920, shot_id="sh_01"))
