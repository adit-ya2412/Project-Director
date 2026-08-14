"""FalQueueClient tests using a fake stand-in for `fal_client.AsyncClient`
- no real network. Reuses the SDK's own `Completed` dataclass for status
responses, since that's public, stable API surface; only the
HTTP-calling client/handle objects are faked."""

import fal_client
import httpx
import pytest

from app.core.errors import PermanentError, TransientError
from app.providers.fal_queue import FalQueueClient


class _FakeHandle:
    def __init__(self, status: fal_client.Status, result: dict | None = None) -> None:
        self._status = status
        self._result = result

    async def status(self, with_logs: bool = False) -> fal_client.Status:
        return self._status

    async def get(self) -> dict:
        assert self._result is not None
        return self._result


class _FakeSubmitHandle:
    def __init__(self, request_id: str) -> None:
        self.request_id = request_id


class _FakeFalClient:
    def __init__(self, *, submit_request_id: str = "job-1", submit_error=None, handle=None) -> None:
        self.submit_calls: list[tuple[str, dict]] = []
        self._submit_request_id = submit_request_id
        self._submit_error = submit_error
        self._handle = handle

    async def submit(self, model_id: str, arguments: dict):
        self.submit_calls.append((model_id, arguments))
        if self._submit_error:
            raise self._submit_error
        return _FakeSubmitHandle(self._submit_request_id)

    async def get_handle(self, model_id: str, request_id: str):
        return self._handle


def _http_error(status_code: int) -> fal_client.FalClientHTTPError:
    response = httpx.Response(status_code, request=httpx.Request("GET", "https://fal.run/x"))
    return fal_client.FalClientHTTPError(
        f"error {status_code}", status_code=status_code, response_headers={}, response=response
    )


async def test_submit_returns_request_id():
    fake = _FakeFalClient(submit_request_id="job-42")
    client = FalQueueClient(fake)
    job_id = await client.submit("fal-ai/some-model", {"prompt": "x"})
    assert job_id == "job-42"
    assert fake.submit_calls == [("fal-ai/some-model", {"prompt": "x"})]


async def test_submit_maps_429_to_transient_error():
    fake = _FakeFalClient(submit_error=_http_error(429))
    client = FalQueueClient(fake)
    with pytest.raises(TransientError):
        await client.submit("fal-ai/some-model", {})


async def test_submit_maps_404_to_permanent_error_mentioning_the_model(monkeypatch):
    fake = _FakeFalClient(submit_error=_http_error(404))
    client = FalQueueClient(fake)
    with pytest.raises(PermanentError, match="fal-ai/missing-model"):
        await client.submit("fal-ai/missing-model", {})


async def test_poll_once_reports_in_progress_for_queued_and_in_progress_states():
    for status in (fal_client.Queued(position=1), fal_client.InProgress(logs=None)):
        fake = _FakeFalClient(handle=_FakeHandle(status))
        client = FalQueueClient(fake)
        state, result, error = await client.poll_once("fal-ai/some-model", "job-1")
        assert state == "in_progress"
        assert result is None and error is None


async def test_poll_once_returns_completed_result():
    completed = fal_client.Completed(logs=None, metrics={}, error=None)
    fake = _FakeFalClient(handle=_FakeHandle(completed, result={"images": [{"url": "http://x"}]}))
    client = FalQueueClient(fake)
    state, result, error = await client.poll_once("fal-ai/some-model", "job-1")
    assert state == "completed"
    assert result == {"images": [{"url": "http://x"}]}
    assert error is None


async def test_poll_once_reports_failed_when_completed_carries_an_error():
    completed = fal_client.Completed(logs=None, metrics={}, error="model exploded")
    fake = _FakeFalClient(handle=_FakeHandle(completed))
    client = FalQueueClient(fake)
    state, result, error = await client.poll_once("fal-ai/some-model", "job-1")
    assert state == "failed"
    assert error == "model exploded"
    assert result is None


async def test_poll_once_maps_5xx_to_transient_error():
    class _RaisingHandle:
        async def status(self, with_logs: bool = False):
            raise _http_error(503)

    fake = _FakeFalClient(handle=_RaisingHandle())
    client = FalQueueClient(fake)
    with pytest.raises(TransientError):
        await client.poll_once("fal-ai/some-model", "job-1")
