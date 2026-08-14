"""Real video generation via fal.ai (M7, ladder rung 5). Model:
`fal-ai/kling-video/o3/standard/image-to-video` by default - image-to-
video, not text-to-video, so every submission needs a source keyframe
URL (generated via `FalImageProvider` first - see
`ResolveAssetsStep._generate_video_real`).

Submit/poll, never blocks to completion (implementation guide, Phase M7
advice: "video generation is submit-and-poll... minutes, sometimes tens
of minutes... the workflow engine must survive process restarts").
`submit` returns a job id the caller persists immediately, before
anything else; `poll` is called at most once per workflow attempt.
"""

import httpx

from app.core.config import settings
from app.core.errors import TransientError
from app.providers.base import VideoJobStatus, VideoRequest
from app.providers.fal_queue import FalQueueClient

_MIN_DURATION_S = 3
_MAX_DURATION_S = 15


class FalVideoProvider:
    name = "fal_video"

    def __init__(
        self,
        queue_client: FalQueueClient | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._queue = queue_client or FalQueueClient()
        self._model_id = settings.fal_video_model
        self._transport = transport

    async def submit(self, request: VideoRequest) -> str:
        duration = max(_MIN_DURATION_S, min(_MAX_DURATION_S, round(request.duration_s)))
        arguments = {
            "image_url": request.image_url,
            "prompt": request.prompt,
            "duration": str(duration),
        }
        return await self._queue.submit(self._model_id, arguments)

    async def poll(self, job_id: str) -> VideoJobStatus:
        state, result, error = await self._queue.poll_once(self._model_id, job_id)
        if state == "in_progress":
            return VideoJobStatus(state="in_progress")
        if state == "failed":
            return VideoJobStatus(state="failed", error=error)

        video = (result or {}).get("video") or {}
        url = video.get("url")
        if not url:
            return VideoJobStatus(
                state="failed", error=f"fal video model {self._model_id!r} returned no video url"
            )
        content = await self._download(url)
        return VideoJobStatus(
            state="completed", content=content, content_type=video.get("content_type", "video/mp4")
        )

    async def _download(self, url: str) -> bytes:
        try:
            async with httpx.AsyncClient(timeout=120.0, transport=self._transport) as client:
                response = await client.get(url, follow_redirects=True)
                response.raise_for_status()
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise TransientError(f"failed to download generated video: {exc}") from exc
        except httpx.HTTPStatusError as exc:
            raise TransientError(f"failed to download generated video: {exc}") from exc
        return response.content
