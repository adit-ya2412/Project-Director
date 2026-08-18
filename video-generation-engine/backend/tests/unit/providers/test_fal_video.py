"""FalVideoProvider tests - a fake FalQueueClient stands in for the real
fal.ai queue (no network), and httpx.MockTransport stands in for the
downloaded video bytes."""

import httpx

from app.providers.base import VideoRequest
from app.providers.fal_video import FalVideoProvider


class _FakeQueueClient:
    def __init__(self, poll_result=None) -> None:
        self.submit_calls: list[tuple[str, dict]] = []
        self._poll_result = poll_result

    async def submit(self, model_id: str, arguments: dict) -> str:
        self.submit_calls.append((model_id, arguments))
        return "job-video-1"

    async def poll_once(self, model_id: str, job_id: str):
        return self._poll_result


def _download_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, content=b"fake-video-bytes", headers={"content-type": "video/mp4"})


async def test_submit_sends_image_url_prompt_and_clamped_duration():
    queue = _FakeQueueClient()
    provider = FalVideoProvider(queue)

    await provider.submit(
        VideoRequest(
            prompt="a slow pan",
            image_url="http://fal.example/keyframe.jpg",
            duration_s=3.0,
            shot_id="sh_01",
        )
    )

    _model_id, arguments = queue.submit_calls[0]
    assert arguments["image_url"] == "http://fal.example/keyframe.jpg"
    assert arguments["prompt"] == "a slow pan"
    assert arguments["duration"] == "3"


async def test_submit_disables_generated_audio():
    """A3 (motion_new_styles_and_long_form_videos.md, 2026-08-18):
    narration is the only voice (D1) - the request must not ride the
    model's own undocumented `generate_audio` default."""
    queue = _FakeQueueClient()
    provider = FalVideoProvider(queue)

    await provider.submit(
        VideoRequest(
            prompt="a slow pan",
            image_url="http://fal.example/keyframe.jpg",
            duration_s=3.0,
            shot_id="sh_01",
        )
    )

    _model_id, arguments = queue.submit_calls[0]
    assert arguments["generate_audio"] is False


async def test_submit_clamps_duration_to_the_allowed_range():
    queue = _FakeQueueClient()
    provider = FalVideoProvider(queue)

    await provider.submit(
        VideoRequest(prompt="p", image_url="http://x", duration_s=45.0, shot_id="sh_01")
    )
    await provider.submit(
        VideoRequest(prompt="p", image_url="http://x", duration_s=0.5, shot_id="sh_01")
    )

    assert queue.submit_calls[0][1]["duration"] == "15"
    assert queue.submit_calls[1][1]["duration"] == "3"


async def test_poll_returns_in_progress():
    queue = _FakeQueueClient(poll_result=("in_progress", None, None))
    provider = FalVideoProvider(queue)
    status = await provider.poll("job-video-1")
    assert status.state == "in_progress"


async def test_poll_returns_failed_with_error():
    queue = _FakeQueueClient(poll_result=("failed", None, "generation blocked"))
    provider = FalVideoProvider(queue)
    status = await provider.poll("job-video-1")
    assert status.state == "failed"
    assert status.error == "generation blocked"


async def test_poll_downloads_completed_video():
    queue = _FakeQueueClient(
        poll_result=("completed", {"video": {"url": "http://fal.example/out.mp4"}}, None)
    )
    provider = FalVideoProvider(queue, transport=httpx.MockTransport(_download_handler))

    status = await provider.poll("job-video-1")

    assert status.state == "completed"
    assert status.content == b"fake-video-bytes"
    assert status.content_type == "video/mp4"


async def test_poll_reports_failed_when_result_has_no_video_url():
    queue = _FakeQueueClient(poll_result=("completed", {"video": {}}, None))
    provider = FalVideoProvider(queue)
    status = await provider.poll("job-video-1")
    assert status.state == "failed"
    assert status.error is not None
