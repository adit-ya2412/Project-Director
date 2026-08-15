"""Project, script, render, and workflow endpoints (docs/09_API_Specification.md).

`POST /render` starts (or resumes) the workflow engine and returns
whatever the pipeline reaches: `awaiting_approval`, `completed`, or
`failed`. `POST /timeline/approve` approves the active timeline and
resumes the same run - the human-in-the-loop gate (ADR-008) is a real
stop between two separate HTTP calls, not a blocked coroutine.
"""

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_repo, get_timeline_service, get_workflow_engine
from app.assets.cost import estimate_project_cost_cents
from app.db.session import get_db
from app.repositories.generated_clip_repository import GeneratedClipRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.shot_binding_repository import ShotBindingRepository
from app.repositories.workflow_repository import WorkflowRunRepository
from app.schemas.project import Project, ProjectStatus
from app.schemas.timeline import Timeline, TimelineStatus
from app.timeline.service import TimelineService
from app.workflow.engine import WorkflowEngine

router = APIRouter(prefix="/projects", tags=["projects"])

_TERMINAL_SHOT_STATES = ("resolved", "generated")


class CreateProjectRequest(BaseModel):
    name: str


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
    shots_detail = [
        {
            "shot_id": b.shot_id,
            "state": b.state,
            "rung": b.rung,
            "last_error": b.last_error,
        }
        for b in sorted(bindings, key=lambda b: b.shot_id)
    ]

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
