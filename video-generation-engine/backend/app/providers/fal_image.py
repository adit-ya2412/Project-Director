"""Real image generation via fal.ai (M7, ladder rung 6). Model:
`fal-ai/bytedance/seedream/v4/text-to-image` by default (config value,
never hardcoded here - implementation guide, Phase M7 advice).

Bounded synchronous poll: Seedream typically resolves in a few seconds,
so unlike video generation this does not need cross-request-restart
resumability. A job that genuinely gets stuck surfaces as a
TransientError and the whole shot retries later through the normal
workflow-engine backoff, same as any other transient failure.
"""

import asyncio

import httpx

from app.core.config import settings
from app.core.errors import PermanentError, TransientError
from app.providers.base import ImageRequest, ImageResult
from app.providers.fal_queue import FalQueueClient

_POLL_INTERVAL_S = 2.0
_MAX_POLL_ATTEMPTS = 30  # ~60s bounded wait


class FalImageProvider:
    name = "fal_image"

    def __init__(
        self,
        queue_client: FalQueueClient | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._queue = queue_client or FalQueueClient()
        self._model_id = settings.fal_image_model
        self._transport = transport

    async def generate(self, request: ImageRequest) -> ImageResult:
        arguments: dict = {
            "prompt": request.prompt,
            "image_size": {"width": request.width, "height": request.height},
            "num_images": 1,
        }
        if request.seed is not None:
            arguments["seed"] = request.seed

        job_id = await self._queue.submit(self._model_id, arguments)

        for _ in range(_MAX_POLL_ATTEMPTS):
            state, result, error = await self._queue.poll_once(self._model_id, job_id)
            if state == "completed":
                return await self._to_result(result)
            if state == "failed":
                raise PermanentError(f"fal image generation failed: {error}")
            await asyncio.sleep(_POLL_INTERVAL_S)

        raise TransientError(
            f"fal image generation for model {self._model_id!r} did not complete within "
            f"{_MAX_POLL_ATTEMPTS * _POLL_INTERVAL_S:.0f}s"
        )

    async def _to_result(self, result: dict | None) -> ImageResult:
        images = (result or {}).get("images") or []
        if not images:
            raise PermanentError(f"fal image model {self._model_id!r} returned no images")
        image = images[0]
        url = image["url"]
        content = await self._download(url)
        return ImageResult(
            content=content,
            content_type=image.get("content_type", "image/jpeg"),
            hosted_url=url,
        )

    async def _download(self, url: str) -> bytes:
        try:
            async with httpx.AsyncClient(timeout=30.0, transport=self._transport) as client:
                response = await client.get(url, follow_redirects=True)
                response.raise_for_status()
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise TransientError(f"failed to download generated image: {exc}") from exc
        except httpx.HTTPStatusError as exc:
            raise TransientError(f"failed to download generated image: {exc}") from exc
        return response.content
