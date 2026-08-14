"""Fake planning pipeline.

Stands in for the entire Director -> Scene Planner -> Shot Planner ->
Asset Planner chain (M5). Loads the hand-written fixture timeline and
re-stamps the identifiers and timestamp for the calling project, so the
render pipeline can be built and tested before a single real LLM prompt
is written.

Real planners land in M5 behind the same call shape: script in, Timeline
out.
"""

import json

from app.core.clock import utcnow
from app.schemas.timeline import Timeline

_FIXTURE_PACKAGE = "tests.fixtures"
_FIXTURE_NAME = "timeline_v1.json"


def _load_fixture() -> dict:
    # tests/ is not a package under app/, so resolve relative to the repo
    # layout directly rather than importlib.resources.
    from pathlib import Path

    fixture_path = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / _FIXTURE_NAME
    return json.loads(fixture_path.read_text(encoding="utf-8"))


class FakeTimelinePlanner:
    """Fake stand-in for the full planning pipeline."""

    async def plan(self, *, project_id: str, script: str) -> Timeline:
        data = _load_fixture()
        data["project_id"] = project_id
        data["timeline_id"] = project_id  # 1:1 for the fixture's single version
        data["created_at"] = utcnow().isoformat()
        return Timeline.model_validate(data)
