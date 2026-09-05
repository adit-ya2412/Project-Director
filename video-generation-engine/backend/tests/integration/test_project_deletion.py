"""`GET /projects/{id}/deletion-preview` and `DELETE /projects/{id}`
(`app/api/projects.py`, logic in `app/projects/deletion.py`).

Runs against the real Postgres test DB (see `tests/conftest.py`), same
as `test_narration_persistence.py` - there is no mocked database for
integration tests in this codebase. Every project id used here is a
fresh `uuid.uuid4()` with a `SMOKETEST-`-prefixed name, and every test
cleans up every row and directory it created in a `finally` block
regardless of outcome - this suite runs against the SAME shared
database real, hand-created projects live in, and must never leave
anything behind for a stray future scan (`_narration_dependencies`/
`_generated_clip_dependencies` scan every OTHER project's rows) to trip
over.

The router is mounted with NO dependency overrides - `get_db` resolves
to the real session factory exactly as a live server would, so this
exercises the actual endpoint wiring, not a faked stand-in for it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

import app.api.projects as projects_module
from app.core.config import settings
from app.db.session import async_session_factory
from app.models.asset import AssetModel
from app.models.domain_event import DomainEventModel
from app.models.generated_clip import GeneratedClipModel
from app.models.llm_call import LlmCallModel
from app.models.narration import NarrationModel
from app.models.project import ProjectModel
from app.models.render import RenderModel
from app.models.script import ScriptModel
from app.models.shot_binding import ShotBindingModel
from app.models.timeline_version import TimelineVersionModel
from app.models.workflow import WorkflowRunModel, WorkflowStepAttemptModel
from app.providers.elevenlabs import compute_narration_content_hash
from app.schemas.timeline import ProducedBy, Scene, Timeline, TimelineMetadata, TimelineStatus
from app.script.styles import resolve_narration_speed

_ALL_CHILD_MODELS = (
    AssetModel,
    GeneratedClipModel,
    NarrationModel,
    RenderModel,
    ScriptModel,
    TimelineVersionModel,
    DomainEventModel,
    LlmCallModel,
)


def _build_client() -> AsyncClient:
    app = FastAPI()
    app.include_router(projects_module.router)
    # No "/api/v1" prefix here - that's added by the real ASGI app
    # mount (main.py), not by this router itself; the router's own
    # paths start straight from "/projects".
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _hard_cleanup(*project_ids: uuid.UUID) -> None:
    """Best-effort teardown independent of the code under test - deletes
    every row this suite could plausibly have created for the given
    project ids, swallowing errors so one already-cleaned-up table never
    stops the rest from being swept.

    ALL `shot_binding` rows for EVERY given project id are removed in one
    first pass, BEFORE any `asset`/`generated_clip` row is touched -
    caught the hard way once already: the cross-project dependency
    tests deliberately make project B's binding point at project A's
    clip, and cleaning project A up first (with project B's binding
    still alive) hit the exact FK-violation `delete_project` itself
    exists to avoid, aborted THAT project's whole cleanup transaction,
    and silently left every one of project A's rows behind (the
    `except Exception` below is a safety net for genuinely unexpected
    failures, not a substitute for getting this ordering right)."""
    async with async_session_factory() as session:
        try:
            await session.execute(
                delete(ShotBindingModel).where(ShotBindingModel.project_id.in_(project_ids))
            )
            await session.commit()
        except Exception:
            await session.rollback()

        for pid in project_ids:
            try:
                run_ids = select(WorkflowRunModel.id).where(WorkflowRunModel.project_id == pid)
                await session.execute(
                    delete(WorkflowStepAttemptModel).where(
                        WorkflowStepAttemptModel.workflow_run_id.in_(run_ids)
                    )
                )
                for model in (*_ALL_CHILD_MODELS, WorkflowRunModel):
                    await session.execute(delete(model).where(model.project_id == pid))
                await session.execute(delete(ProjectModel).where(ProjectModel.id == pid))
                await session.commit()
            except Exception:
                await session.rollback()


async def _seed_full_project(project_id: uuid.UUID, *, name: str) -> tuple[uuid.UUID, uuid.UUID]:
    """One row in every project-scoped table, plus a workflow_run with
    one workflow_step_attempt child and a shot_binding pointing at the
    seeded asset. Returns (asset_id, clip_id) for callers that need to
    reference them (the cross-project dependency tests)."""
    async with async_session_factory() as session:
        session.add(ProjectModel(id=project_id, name=name, status="created"))
        await session.flush()

        session.add(ScriptModel(project_id=project_id, content="hello", version=1, source="user"))
        # A real, parseable Timeline document (not a hand-rolled dict) -
        # this row is never read as "another project's" timeline within
        # THIS test (its own project is always excluded from that scan),
        # but keeping it well-formed avoids planting a landmine for any
        # later test that reuses this seed helper differently.
        seed_timeline = Timeline(
            timeline_id="t_seed",
            project_id=str(project_id),
            version=1,
            produced_by=ProducedBy.HUMAN,
            status=TimelineStatus.DRAFT,
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            scenes=[],
        )
        session.add(
            TimelineVersionModel(
                project_id=project_id,
                version=1,
                parent_version=None,
                produced_by=ProducedBy.HUMAN.value,
                status=TimelineStatus.DRAFT.value,
                document=seed_timeline.model_dump(mode="json"),
            )
        )
        asset = AssetModel(
            project_id=project_id,
            provider="test",
            source_url=None,
            type="image",
            local_path=None,
            licence="unknown",
            attribution=None,
            content_hash=f"asset-{uuid.uuid4().hex}",
            confidence=1.0,
            description=None,
        )
        clip = GeneratedClipModel(
            project_id=project_id,
            shot_id="sh_01",
            provider="test",
            model_id="test-model",
            prompt="a prompt",
            prompt_hash=f"clip-{uuid.uuid4().hex}",
            duration_s=None,
            local_path=None,
            cost_cents=4,
            status="completed",
        )
        narration = NarrationModel(
            project_id=project_id,
            scene_id="sc_01",
            provider="test",
            voice_id="v1",
            model_id="m1",
            output_format="mp3",
            text="hi",
            content_hash=f"narr-{uuid.uuid4().hex}",
            local_path="unused.mp3",
            alignment={"characters": []},
            character_count=2,
            cost_cents=1,
        )
        session.add_all([asset, clip, narration])
        session.add(
            RenderModel(
                project_id=project_id,
                status="completed",
                output_path=None,
                fingerprint=None,
                settings={},
                is_draft=False,
            )
        )
        session.add(DomainEventModel(project_id=project_id, event_type="Test", payload={}))
        session.add(
            LlmCallModel(
                project_id=project_id,
                agent="director",
                prompt_version=None,
                model="m",
                request={},
                response={},
                input_tokens=None,
                output_tokens=None,
                cost_cents=None,
                input_usd_per_1m=None,
                output_usd_per_1m=None,
            )
        )
        run = WorkflowRunModel(
            project_id=project_id, state="completed", progress=1.0, current_step=None
        )
        session.add(run)
        await session.flush()

        session.add(
            ShotBindingModel(
                project_id=project_id,
                timeline_version=1,
                shot_id="sh_01",
                state="resolved",
                asset_id=asset.id,
                clip_id=None,
            )
        )
        session.add(
            WorkflowStepAttemptModel(
                workflow_run_id=run.id, step_name="render", attempt_number=1, status="completed"
            )
        )
        await session.commit()
        return asset.id, clip.id


async def _project_row_exists(project_id: uuid.UUID) -> bool:
    async with async_session_factory() as session:
        return (await session.get(ProjectModel, project_id)) is not None


# -- every child table + storage -----------------------------------------


async def test_delete_removes_every_child_table_and_the_project_row(tmp_path):
    project_id = uuid.uuid4()
    await _seed_full_project(project_id, name="SMOKETEST-full-project")
    storage_dir = settings.storage_root / str(project_id)
    storage_dir.mkdir(parents=True, exist_ok=True)
    (storage_dir / "renders").mkdir()
    (storage_dir / "renders" / "final.mp4").write_bytes(b"not-really-a-video")

    try:
        async with _build_client() as client:
            preview_res = await client.get(f"/projects/{project_id}/deletion-preview")
            assert preview_res.status_code == 200, preview_res.text
            preview = preview_res.json()
            assert preview["row_counts"] == {
                "workflow_step_attempt": 1,
                "workflow_run": 1,
                "shot_binding": 1,
                "asset": 1,
                "generated_clip": 1,
                "narration": 1,
                "render": 1,
                "script": 1,
                "timeline_version": 1,
                "domain_event": 1,
                "llm_call": 1,
            }
            assert preview["storage_exists"] is True
            assert preview["storage_bytes"] == len(b"not-really-a-video")

            delete_res = await client.delete(f"/projects/{project_id}")
            assert delete_res.status_code == 200, delete_res.text
            summary = delete_res.json()
            # DELETE reports the same counts the preview promised - what
            # was actually removed, captured before it was.
            assert summary["row_counts"] == preview["row_counts"]

        assert not storage_dir.exists()
        assert await _project_row_exists(project_id) is False

        async with async_session_factory() as session:
            for model in _ALL_CHILD_MODELS:
                remaining = (
                    (await session.execute(select(model).where(model.project_id == project_id)))
                    .scalars()
                    .all()
                )
                assert remaining == [], f"{model.__tablename__} still has rows: {remaining}"
            remaining_bindings = (
                (
                    await session.execute(
                        select(ShotBindingModel).where(ShotBindingModel.project_id == project_id)
                    )
                )
                .scalars()
                .all()
            )
            assert remaining_bindings == []
            remaining_runs = (
                (
                    await session.execute(
                        select(WorkflowRunModel).where(WorkflowRunModel.project_id == project_id)
                    )
                )
                .scalars()
                .all()
            )
            assert remaining_runs == []
    finally:
        if storage_dir.exists():
            import shutil

            shutil.rmtree(storage_dir)
        await _hard_cleanup(project_id)


# -- 404 for a project that does not exist --------------------------------


async def test_deletion_preview_404s_for_a_nonexistent_project():
    async with _build_client() as client:
        res = await client.get(f"/projects/{uuid.uuid4()}/deletion-preview")
        assert res.status_code == 404


async def test_delete_404s_for_a_nonexistent_project():
    async with _build_client() as client:
        res = await client.delete(f"/projects/{uuid.uuid4()}")
        assert res.status_code == 404


async def test_delete_404s_for_a_malformed_uuid_rather_than_erroring():
    """Same "not a well-formed UUID -> can't possibly match a row, same
    externally-visible outcome as not found" precedent
    `PostgresProjectRepository.get` already sets - never a path escape
    attempt or a 500."""
    async with _build_client() as client:
        res = await client.delete("/projects/not-a-uuid-at-all")
        assert res.status_code == 404


# -- cross-project narration dependency (the test that matters most) -----


async def test_deletion_preview_reports_a_narration_row_another_project_depends_on():
    project_a = uuid.uuid4()
    project_b = uuid.uuid4()
    shared_text = "This exact sentence is shared between two throwaway test projects."
    voice_id = "voice_shared_test_project_deletion"
    model = settings.elevenlabs_model
    output_format = settings.elevenlabs_output_format
    language_code = settings.elevenlabs_language_code
    speed = resolve_narration_speed(None)
    content_hash = compute_narration_content_hash(
        text=shared_text,
        voice_id=voice_id,
        model=model,
        output_format=output_format,
        speed=speed,
        language_code=language_code,
    )

    try:
        async with async_session_factory() as session:
            session.add(ProjectModel(id=project_a, name="SMOKETEST-narration-owner", status="created"))
            session.add(
                ProjectModel(id=project_b, name="SMOKETEST-narration-dependent", status="created")
            )
            await session.flush()

            session.add(
                NarrationModel(
                    project_id=project_a,
                    scene_id="sc_01",
                    provider="test",
                    voice_id=voice_id,
                    model_id=model,
                    output_format=output_format,
                    text=shared_text,
                    content_hash=content_hash,
                    local_path="unused.mp3",
                    alignment={"characters": []},
                    character_count=len(shared_text),
                    cost_cents=7,
                )
            )

            # Project B has NEVER synthesised its own narration row for
            # this text - its own next lookup has always resolved to
            # project A's row above. That is precisely the dependency
            # this preview must catch WITHOUT B owning any narration row
            # of its own.
            dependent_timeline = Timeline(
                timeline_id="t_b",
                project_id=str(project_b),
                version=1,
                produced_by=ProducedBy.NARRATION,
                status=TimelineStatus.DRAFT,
                created_at=datetime(2026, 1, 1, tzinfo=UTC),
                metadata=TimelineMetadata(
                    narration_locked=True, voice_id=voice_id, language_code=language_code
                ),
                scenes=[
                    Scene(
                        id="sc_b1",
                        order=0,
                        title="shared scene",
                        duration_s=3.0,
                        narration_text=shared_text,
                    )
                ],
            )
            session.add(
                TimelineVersionModel(
                    project_id=project_b,
                    version=1,
                    parent_version=None,
                    produced_by=ProducedBy.NARRATION.value,
                    status=TimelineStatus.DRAFT.value,
                    document=dependent_timeline.model_dump(mode="json"),
                )
            )
            await session.commit()

        async with _build_client() as client:
            res = await client.get(f"/projects/{project_a}/deletion-preview")
        assert res.status_code == 200, res.text
        preview = res.json()

        assert len(preview["narration_dependencies"]) == 1
        dep = preview["narration_dependencies"][0]
        assert dep["depended_on_by_project_id"] == str(project_b)
        assert dep["depended_on_by_project_name"] == "SMOKETEST-narration-dependent"
        assert dep["depended_on_by_scene_id"] == "sc_b1"
        assert dep["content_hash"] == content_hash
        assert dep["respend_estimate_cents"] == 7
        assert preview["affected_project_ids"] == [str(project_b)]
        assert preview["total_respend_estimate_cents"] == 7
    finally:
        await _hard_cleanup(project_a, project_b)


async def test_a_project_with_no_narration_reuse_reports_no_dependency():
    """Negative control for the test above - two projects, unrelated
    text, must not spuriously report a dependency."""
    project_a = uuid.uuid4()
    project_b = uuid.uuid4()
    try:
        async with async_session_factory() as session:
            session.add(ProjectModel(id=project_a, name="SMOKETEST-no-dep-A", status="created"))
            session.add(ProjectModel(id=project_b, name="SMOKETEST-no-dep-B", status="created"))
            await session.flush()
            session.add(
                NarrationModel(
                    project_id=project_a,
                    scene_id="sc_01",
                    provider="test",
                    voice_id="v_a_only",
                    model_id="m1",
                    output_format="mp3",
                    text="text nobody else ever narrates",
                    content_hash=f"unshared-{uuid.uuid4().hex}",
                    local_path="unused.mp3",
                    alignment={"characters": []},
                    character_count=10,
                    cost_cents=3,
                )
            )
            timeline = Timeline(
                timeline_id="t_b2",
                project_id=str(project_b),
                version=1,
                produced_by=ProducedBy.NARRATION,
                status=TimelineStatus.DRAFT,
                created_at=datetime(2026, 1, 1, tzinfo=UTC),
                metadata=TimelineMetadata(narration_locked=True, voice_id="v_b_only"),
                scenes=[
                    Scene(
                        id="sc_b2",
                        order=0,
                        title="unrelated scene",
                        duration_s=2.0,
                        narration_text="completely different narration text",
                    )
                ],
            )
            session.add(
                TimelineVersionModel(
                    project_id=project_b,
                    version=1,
                    parent_version=None,
                    produced_by=ProducedBy.NARRATION.value,
                    status=TimelineStatus.DRAFT.value,
                    document=timeline.model_dump(mode="json"),
                )
            )
            await session.commit()

        async with _build_client() as client:
            res = await client.get(f"/projects/{project_a}/deletion-preview")
        assert res.status_code == 200, res.text
        preview = res.json()
        assert preview["narration_dependencies"] == []
        assert preview["affected_project_ids"] == []
    finally:
        await _hard_cleanup(project_a, project_b)


# -- cross-project generated_clip dependency + release on delete ---------


async def test_delete_releases_another_projects_binding_to_a_deleted_clip():
    project_a = uuid.uuid4()
    project_b = uuid.uuid4()
    try:
        _asset_id, clip_id = await _seed_full_project(project_a, name="SMOKETEST-clip-owner")

        async with async_session_factory() as session:
            session.add(ProjectModel(id=project_b, name="SMOKETEST-clip-dependent", status="created"))
            await session.flush()
            session.add(
                ShotBindingModel(
                    project_id=project_b,
                    timeline_version=1,
                    shot_id="sh_b1",
                    state="generated",
                    clip_id=clip_id,
                    secondary_clip_id=clip_id,
                    secondary_state="generated",
                )
            )
            await session.commit()

        async with _build_client() as client:
            preview_res = await client.get(f"/projects/{project_a}/deletion-preview")
            assert preview_res.status_code == 200, preview_res.text
            preview = preview_res.json()
            panels = {d["panel"] for d in preview["generated_clip_dependencies"]}
            assert panels == {"primary", "secondary"}
            assert preview["affected_project_ids"] == [str(project_b)]

            delete_res = await client.delete(f"/projects/{project_a}")
            assert delete_res.status_code == 200, delete_res.text

        async with async_session_factory() as session:
            binding = (
                await session.execute(
                    select(ShotBindingModel).where(ShotBindingModel.project_id == project_b)
                )
            ).scalar_one()
            assert binding.clip_id is None
            assert binding.state == "pending"
            assert binding.secondary_clip_id is None
            assert binding.secondary_state == "pending"
    finally:
        storage_dir = settings.storage_root / str(project_a)
        if storage_dir.exists():
            import shutil

            shutil.rmtree(storage_dir)
        await _hard_cleanup(project_a, project_b)
