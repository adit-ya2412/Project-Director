"""Thin wrapper around fal.ai's queue (M7) - the only file that imports
the `fal_client` SDK. Generic over any model on fal's queue: submit once,
poll once per call, never block to completion. That single rule is what
lets a video job survive a process restart (implementation guide, Phase
M7 advice: "fal's queue exposes the same submit/status/result shape for
every model, so write this once against the queue rather than per
model").
"""

import fal_client

from app.core.config import settings
from app.core.errors import PermanentError, TransientError

_TRANSIENT_STATUS_CODES = frozenset({408, 425, 429, 500, 502, 503, 504})


def _map_error(exc: fal_client.FalClientHTTPError, model_id: str) -> Exception:
    if exc.status_code == 404:
        return PermanentError(
            f"fal model {model_id!r} not found (404) - it may have moved; check "
            f"https://fal.ai/models and update the .env value"
        )
    if exc.status_code in _TRANSIENT_STATUS_CODES:
        return TransientError(f"fal request to {model_id!r} failed ({exc.status_code}): {exc}")
    return PermanentError(f"fal request to {model_id!r} failed ({exc.status_code}): {exc}")


class FalQueueClient:
    def __init__(self, client: fal_client.AsyncClient | None = None) -> None:
        self._client = client or fal_client.AsyncClient(key=settings.fal_key)

    async def submit(self, model_id: str, arguments: dict) -> str:
        try:
            handle = await self._client.submit(model_id, arguments=arguments)
        except fal_client.FalClientHTTPError as exc:
            raise _map_error(exc, model_id) from exc
        return handle.request_id

    async def poll_once(self, model_id: str, job_id: str) -> tuple[str, dict | None, str | None]:
        """One status check, never blocks until completion. Returns
        (state, result, error) where state is "in_progress" | "completed"
        | "failed"."""
        handle = await self._client.get_handle(model_id, job_id)
        try:
            status = await handle.status()
        except fal_client.FalClientHTTPError as exc:
            raise _map_error(exc, model_id) from exc

        if not isinstance(status, fal_client.Completed):
            return "in_progress", None, None
        if status.error:
            return "failed", None, status.error

        try:
            result = await handle.get()
        except fal_client.FalClientHTTPError as exc:
            raise _map_error(exc, model_id) from exc
        return "completed", result, None
