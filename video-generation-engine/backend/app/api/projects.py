"""Project, script, render, and workflow endpoints (docs/09_API_Specification.md).

`POST /render` starts (or resumes) the workflow engine and returns
whatever the pipeline reaches: `awaiting_approval`, `awaiting_review`,
`completed`, or `failed`. `POST /timeline/approve` approves the active
timeline and resumes the same run - the human-in-the-loop gate (ADR-008)
is a real stop between two separate HTTP calls, not a blocked coroutine.

`POST /{id}/assets` (M6.5, A8/A23/A27) and
`POST /{id}/shots/{shot_id}/override` (M6.5, A9/A10/A24/A25/A29) are the
two human-media endpoints this phase adds - an optional upload matched to
shots later by the existing relevance gate, and a per-shot override that
bypasses every gate and locks that shot's asset. Neither one runs the
workflow engine synchronously except the override, which resumes it
(A26's only remedy for a shot stuck `failed` at the review gate).
"""

import hashlib
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_repo, get_timeline_service, get_workflow_engine
from app.assets.cost import estimate_project_cost_cents
from app.assets.validation import validate_and_identify_image
from app.core.config import settings
from app.core.errors import PermanentError
from app.db.session import get_db
from app.models.asset import AssetModel
from app.models.generated_clip import GeneratedClipModel
from app.repositories.asset_repository import AssetRepository
from app.repositories.generated_clip_repository import GeneratedClipRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.shot_binding_repository import ShotBindingRepository
from app.repositories.workflow_repository import WorkflowRunRepository
from app.schemas.project import Project, ProjectStatus
from app.schemas.timeline import ProducedBy, Timeline, TimelineStatus
from app.timeline.service import TimelineService
from app.workflow.engine import WorkflowEngine

router = APIRouter(prefix="/projects", tags=["projects"])

_TERMINAL_SHOT_STATES = ("resolved", "generated")


class CreateProjectRequest(BaseModel):
    name: str


class UploadedAssetResult(BaseModel):
    asset_id: str
    filename: str
    duplicate: bool


class UploadScriptRequest(BaseModel):
    content: str


async def _get_project_or_404(project_id: str, repo: ProjectRepository) -> Project:
    project = await repo.get(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"project {project_id} not found")
    return project


@router.post("", response_model=Project)
async def create_project(
    body: CreateProjectRequest,
    repo: ProjectRepository = Depends(get_repo),
) -> Project:
    return await repo.create(name=body.name)


@router.get("", response_model=list[Project])
async def list_projects(
    repo: ProjectRepository = Depends(get_repo),
) -> list[Project]:
    return await repo.list_all()


@router.get("/{project_id}", response_model=Project)
async def get_project(project_id: str, repo: ProjectRepository = Depends(get_repo)) -> Project:
    return await _get_project_or_404(project_id, repo)


@router.post("/{project_id}/script", response_model=Project)
async def upload_script(
    project_id: str,
    body: UploadScriptRequest,
    repo: ProjectRepository = Depends(get_repo),
) -> Project:
    project = await _get_project_or_404(project_id, repo)
    if not body.content.strip():
        raise HTTPException(status_code=400, detail="script content must not be empty")
    project.script = body.content
    project.status = ProjectStatus.SCRIPT_UPLOADED
    return await repo.update(project)


@router.get("/{project_id}/script")
async def get_script(project_id: str, repo: ProjectRepository = Depends(get_repo)) -> dict:
    project = await _get_project_or_404(project_id, repo)
    return {"project_id": project.id, "content": project.script}


@router.post("/{project_id}/assets", response_model=list[UploadedAssetResult])
async def upload_assets(
    project_id: str,
    files: list[UploadFile] = File(...),
    descriptions: list[str] = Form(...),
    repo: ProjectRepository = Depends(get_repo),
    session: AsyncSession = Depends(get_db),
) -> list[UploadedAssetResult]:
    """M6.5, A8/A23/A27: media a human already has for this project,
    supplied alongside the script - entirely optional; a project that
    never calls this endpoint behaves exactly as it did before M6.5
    (`LocalProjectAssetProvider.search` returns `[]` and the ladder falls
    through unchanged). Each file carries its own short human-written
    `description` - matching against a filename would be worthless (A23)
    - and is validated and hashed on arrival (A27): the same
    `validate_and_identify_image` path every searched asset already goes
    through, so a file that claims to be an image and isn't fails HERE,
    not inside ffmpeg during the render. Matching to a specific shot
    happens later, automatically, through the existing relevance gate
    (`app/assets/relevance.py`) the next time `resolve_assets_search`
    runs - never here, and never through a planner (A3 stands)."""
    await _get_project_or_404(project_id, repo)
    if not files:
        raise HTTPException(status_code=400, detail="at least one file is required")
    if len(files) != len(descriptions):
        raise HTTPException(
            status_code=400,
            detail=f"{len(files)} file(s) but {len(descriptions)} description(s) - "
            "exactly one description per file is required",
        )

    project_uuid = uuid.UUID(project_id)
    asset_repo = AssetRepository(session)
    assets_dir = settings.storage_root / project_id / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    results: list[UploadedAssetResult] = []
    for upload, description in zip(files, descriptions, strict=True):
        if not description.strip():
            raise HTTPException(
                status_code=400,
                detail=f"{upload.filename}: a description is required (A23) - matching "
                "against a filename alone is not reliable",
            )
        content = await upload.read()
        try:
            ext, _width, _height = validate_and_identify_image(content)
        except PermanentError as exc:
            raise HTTPException(status_code=400, detail=f"{upload.filename}: {exc}") from exc

        content_hash = hashlib.sha256(content).hexdigest()
        existing = await asset_repo.get_by_content_hash(project_uuid, content_hash)
        if existing is not None:
            # Same bytes already on file for this project (M6, hash
            # dedup) - not an error, just nothing new to store.
            results.append(
                UploadedAssetResult(
                    asset_id=str(existing.id), filename=upload.filename or "", duplicate=True
                )
            )
            continue

        path = assets_dir / f"{content_hash}.{ext}"
        path.write_bytes(content)
        asset = await asset_repo.insert(
            project_id=project_uuid,
            provider="project_assets",
            source_url=None,
            type="image",
            local_path=str(path),
            licence="human_upload",
            attribution=None,
            content_hash=content_hash,
            confidence=1.0,
            description=description.strip(),
        )
        results.append(
            UploadedAssetResult(
                asset_id=str(asset.id), filename=upload.filename or "", duplicate=False
            )
        )

    await session.commit()
    return results


@router.get("/{project_id}/timeline", response_model=Timeline)
async def get_timeline(
    project_id: str,
    repo: ProjectRepository = Depends(get_repo),
    timeline_service: TimelineService = Depends(get_timeline_service),
) -> Timeline:
    await _get_project_or_404(project_id, repo)
    active = await timeline_service.get_active(project_id)
    if active is None:
        raise HTTPException(status_code=404, detail="no timeline generated yet")
    return active


@router.post("/{project_id}/render", response_model=Project)
async def render_project(
    project_id: str,
    repo: ProjectRepository = Depends(get_repo),
    engine: WorkflowEngine = Depends(get_workflow_engine),
) -> Project:
    """Starts (or resumes) the workflow engine. Runs synchronously up to
    whatever it reaches next - AWAITING_APPROVAL, COMPLETED, or FAILED.
    A real task queue (background execution) is a later refinement; the
    step contract underneath doesn't change when that lands."""
    project = await _get_project_or_404(project_id, repo)
    if not project.script:
        raise HTTPException(status_code=400, detail="upload a script before rendering")
    return await engine.run()


@router.post("/{project_id}/timeline/approve", response_model=Project)
async def approve_timeline(
    project_id: str,
    repo: ProjectRepository = Depends(get_repo),
    timeline_service: TimelineService = Depends(get_timeline_service),
    engine: WorkflowEngine = Depends(get_workflow_engine),
) -> Project:
    await _get_project_or_404(project_id, repo)
    active = await timeline_service.get_active(project_id)
    if active is None:
        raise HTTPException(status_code=400, detail="no timeline to approve yet")
    if active.status == TimelineStatus.APPROVED:
        raise HTTPException(status_code=400, detail="timeline is already approved")
    await timeline_service.approve(project_id, active.version)
    return await engine.run()


@router.post("/{project_id}/shots/{shot_id}/override", response_model=Project)
async def override_shot_asset(
    project_id: str,
    shot_id: str,
    file: UploadFile = File(...),
    description: str = Form(""),
    repo: ProjectRepository = Depends(get_repo),
    timeline_service: TimelineService = Depends(get_timeline_service),
    engine: WorkflowEngine = Depends(get_workflow_engine),
    session: AsyncSession = Depends(get_db),
) -> Project:
    """M6.5, A9/A10/A24/A25/A29: a human names a shot directly and
    supplies its media themselves. Bypasses relevance and licence gates
    entirely (A24) - a human pointing at a specific shot has already made
    the judgement those gates exist to approximate. Works on ANY shot,
    not only a failed one (a Done-when criterion of this phase is "swap
    or override any of them"), and is also the sole remedy for the A26
    review gate when a shot ends `failed`.

    Recorded as an `append_version` with `produced_by=HUMAN` that sets
    `shot.asset_locked` (A10/A25) - once locked, no later version may
    change that shot's `prompt`/`asset_plan` at all
    (`TimelineService._reject_locked_shot_drift`), and its binding
    carries forward unconditionally across every future version
    (`TimelineService._carry_forward_bindings`). A29: this changes ONLY
    the binding and the lock flag - `duration_s`, narration, framing,
    camera and transitions are never touched, so an override is always a
    free, instant swap, never a paid re-narration.

    Validated and hashed on arrival exactly like the general upload
    endpoint (A27). If the plan was already approved (or narration has
    already run), the new locked version is immediately re-approved too -
    the same "belt and braces" pattern `NarrationStep` already uses to
    append-then-approve in two commits - so resuming via `POST /render`
    below does not demand a redundant second human click for a decision
    already made; a project that had never been approved yet is left in
    DRAFT, so the human's first plan approval is still required as
    normal.
    """
    await _get_project_or_404(project_id, repo)
    active = await timeline_service.get_active(project_id)
    if active is None:
        raise HTTPException(status_code=400, detail="no timeline to override a shot on yet")
    if shot_id not in {s.id for s in active.all_shots()}:
        raise HTTPException(
            status_code=404, detail=f"shot {shot_id} not found in the active timeline"
        )

    content = await file.read()
    try:
        ext, _width, _height = validate_and_identify_image(content)
    except PermanentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    project_uuid = uuid.UUID(project_id)
    asset_repo = AssetRepository(session)
    content_hash = hashlib.sha256(content).hexdigest()
    asset = await asset_repo.get_by_content_hash(project_uuid, content_hash)
    if asset is None:
        assets_dir = settings.storage_root / project_id / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)
        path = assets_dir / f"{content_hash}.{ext}"
        path.write_bytes(content)
        asset = await asset_repo.insert(
            project_id=project_uuid,
            provider="project_assets",
            source_url=None,
            type="image",
            local_path=str(path),
            licence="human_override",
            attribution=None,
            content_hash=content_hash,
            confidence=1.0,
            description=description.strip() or None,
        )

    was_already_approved = active.status == TimelineStatus.APPROVED or (
        active.produced_by == ProducedBy.NARRATION
    )

    def _lock_shot(base: Timeline) -> Timeline:
        for scene in base.scenes:
            for shot in scene.shots:
                if shot.id == shot_id:
                    shot.asset_locked = True
        return base

    new_timeline = await timeline_service.append_version(
        project_id,
        produced_by=ProducedBy.HUMAN,
        transform=_lock_shot,
        owns=frozenset({"scenes"}),
    )

    binding_repo = ShotBindingRepository(session)
    binding = await binding_repo.get_or_create_pending(project_uuid, new_timeline.version, shot_id)
    binding.asset_id = asset.id
    binding.clip_id = None
    binding.state = "resolved"
    binding.rung = "project_assets"
    binding.last_error = None
    await session.flush()

    if was_already_approved:
        await timeline_service.approve(project_id, new_timeline.version)
    await session.commit()

    # An active timeline (checked above) implies a script already exists
    # (`create_initial` requires one) - `engine.run()` always has
    # something to resume from here.
    return await engine.run()


@router.get("/{project_id}/status")
async def get_status(project_id: str, repo: ProjectRepository = Depends(get_repo)) -> dict:
    project = await _get_project_or_404(project_id, repo)
    return {"project_id": project.id, "status": project.status, "error": project.error}


@router.get("/{project_id}/progress")
async def get_progress(
    project_id: str,
    repo: ProjectRepository = Depends(get_repo),
    timeline_service: TimelineService = Depends(get_timeline_service),
    session: AsyncSession = Depends(get_db),
) -> dict:
    """Progress is derived from shot_binding state, never stored as a
    number - a stored percentage drifts the moment anything fails
    (implementation guide, Phase M4 advice)."""
    project = await _get_project_or_404(project_id, repo)
    run_row = await WorkflowRunRepository(session).get_latest(uuid.UUID(project_id))

    base = {
        "project_id": project.id,
        "status": project.status,
        "workflow_state": run_row.state if run_row else None,
        "current_step": run_row.current_step if run_row else None,
    }

    timeline = await timeline_service.get_active(project_id)
    if timeline is None:
        return {
            **base,
            "total_shots": 0,
            "completed_shots": 0,
            "failed_shots": 0,
            "progress": None,
            "estimated_cost_cents": 0,
            "spent_cost_cents": 0,
            "shots": [],
        }

    bindings = await ShotBindingRepository(session).list_for_version(
        uuid.UUID(project_id), timeline.version
    )
    total = len(timeline.all_shots())
    completed = sum(1 for b in bindings if b.state in _TERMINAL_SHOT_STATES)
    failed = sum(1 for b in bindings if b.state == "failed")

    # Per-shot detail - this is the only place shot_binding state is
    # exposed today (M9's dedicated shot-review surface doesn't exist
    # yet), so a failed shot's reason (e.g. a constraint violation that
    # exhausted its regeneration attempts, M6.5 A14/A19) must be visible
    # here rather than only as an aggregate count.
    #
    # M6.5 (A5/A21/A22): the whole point of moving free search before the
    # approval gate is that a human sees, per shot, what was ALREADY
    # FOUND (with its real source - `asset`, populated whenever
    # `asset_id` is set) versus what WILL BE GENERATED
    # (`will_generate`, true exactly when the search-only pass deferred
    # this shot rather than found or failed it). There is no frontend yet
    # (M9) - this is the API surface that stands in for "the human sees
    # the images": the resolved asset's provenance plus its path on disk.
    # M6.5, A9/A10: whether a human already locked this shot's asset via
    # the override endpoint - the other half of "a human can see, and
    # swap or override, any shot's asset" (this phase's Done-when
    # criterion): a locked shot's own state proves the override survives.
    locked_by_shot = {s.id: s.asset_locked for s in timeline.all_shots()}

    shots_detail = []
    for b in sorted(bindings, key=lambda binding: binding.shot_id):
        asset_detail = None
        if b.asset_id is not None:
            asset = await session.get(AssetModel, b.asset_id)
            if asset is not None:
                asset_detail = {
                    "provider": asset.provider,
                    "source_url": asset.source_url,
                    "licence": asset.licence,
                    "attribution": asset.attribution,
                    "local_path": asset.local_path,
                }
        clip_detail = None
        if b.clip_id is not None:
            clip = await session.get(GeneratedClipModel, b.clip_id)
            if clip is not None:
                clip_detail = {
                    "provider": clip.provider,
                    "model_id": clip.model_id,
                    "status": clip.status,
                    "local_path": clip.local_path,
                }
        shots_detail.append(
            {
                "shot_id": b.shot_id,
                "state": b.state,
                "rung": b.rung,
                "last_error": b.last_error,
                "will_generate": b.state == "awaiting_generation",
                "locked": locked_by_shot.get(b.shot_id, False),
                "asset": asset_detail,
                "clip": clip_detail,
            }
        )

    # Estimated before generation runs (implementation guide, Phase M7
    # advice: "estimate cost before the approval gate and show it") -
    # counts only shots already planned to generate; a search-primary shot
    # that later falls through to generation is not reflected here.
    estimated_cost_cents = estimate_project_cost_cents(timeline)
    spent_cost_cents = await GeneratedClipRepository(session).total_cost_cents_for_project(
        uuid.UUID(project_id)
    )

    return {
        **base,
        "total_shots": total,
        "completed_shots": completed,
        "failed_shots": failed,
        "progress": (completed / total) if total else None,
        "estimated_cost_cents": estimated_cost_cents,
        "spent_cost_cents": spent_cost_cents,
        "shots": shots_detail,
    }


@router.get("/{project_id}/video")
async def get_video(project_id: str, repo: ProjectRepository = Depends(get_repo)) -> FileResponse:
    project = await _get_project_or_404(project_id, repo)
    if not project.video_path:
        raise HTTPException(status_code=404, detail="no rendered video for this project yet")
    path = Path(project.video_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="rendered video file is missing on disk")
    return FileResponse(path, media_type="video/mp4", filename=f"{project_id}.mp4")


@router.delete("/{project_id}")
async def delete_project(project_id: str, repo: ProjectRepository = Depends(get_repo)) -> dict:
    await _get_project_or_404(project_id, repo)
    # No delete method on ProjectRepository yet - CASCADE behavior across
    # script/timeline_version/asset/etc. needs deciding first (M3+).
    raise HTTPException(status_code=501, detail="project deletion lands in M3+")
