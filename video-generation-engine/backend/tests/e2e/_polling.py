"""Shared e2e helper (F0a, 2026-08-16): every trigger endpoint that used
to return the whole `Project` synchronously now returns `202` with a
`WorkflowTriggerResult` (a run id, not an outcome) and finishes the work
in the background. Every e2e test that used to read `resp.json()`
straight off a trigger response now polls `GET /status` for a stopping
point and reads the outcome off `GET /projects/{id}` instead - the same
information, fetched the way a real client has to.

Note for anyone surprised this "polling" loop only ever runs once in
practice: `TestClient` drives the app through `httpx`'s ASGI transport
in-process, with no real concurrency between the request and its
`BackgroundTasks` callback - by the time `client.post(...)` returns at
all, the callback has already run to completion. The loop below is
still the right thing to write (it is what a real client against a real
server has to do, and costs nothing extra here), it just always
converges on its first iteration under `TestClient`.
"""

import time

from fastapi.testclient import TestClient

_STOPPING_STATES = frozenset({"awaiting_approval", "awaiting_review", "completed", "failed"})


def wait_for_workflow(
    client: TestClient, project_id: str, *, max_attempts: int = 100, interval_s: float = 0.05
) -> dict:
    """Polls `GET /status` until `project.status` reaches one of the
    states `WorkflowEngine.run()` itself stops at, then returns the full
    `GET /projects/{id}` body - the same shape every trigger endpoint
    used to hand back directly before F0a backgrounded them."""
    for _ in range(max_attempts):
        status = client.get(f"/api/v1/projects/{project_id}/status").json()
        if status["status"] in _STOPPING_STATES:
            break
        time.sleep(interval_s)
    else:
        raise AssertionError(
            f"workflow for project {project_id} never reached a stopping point "
            f"(last status: {status['status']!r})"
        )
    return client.get(f"/api/v1/projects/{project_id}").json()


def trigger_and_wait(client: TestClient, method: str, url: str, **kwargs) -> dict:
    """`client.<method>(url, **kwargs)`, asserted to be the new `202`
    trigger response, then polled to completion - the one-line
    replacement for what used to be `client.post(url).json()` at every
    trigger call site in this test suite."""
    resp = getattr(client, method)(url, **kwargs)
    assert resp.status_code == 202, resp.text
    body = resp.json()
    project_id = body["project_id"]
    return wait_for_workflow(client, project_id)
