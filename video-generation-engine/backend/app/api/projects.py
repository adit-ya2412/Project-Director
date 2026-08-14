"""Project, script, and render endpoints (docs/09_API_Specification.md).

M0 scope only: create project, upload script, render, download. Timeline
review/approval, asset/generation endpoints, and workflow progress arrive
with the phases that back them (M3-M4, M9).
"""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.api.deps import get_repo
from app.repositories.project_repository import InMemoryProjectRepository
from app.schemas.project import Project, ProjectStatus
from app.workflow.pipeline import run_pipeline

router = APIRouter(prefix="/projects", tags=["projects"])


class CreateProjectRequest(BaseModel):
    name: str


class UploadScriptRequest(BaseModel):
    content: str


async def _get_project_or_404(project_id: str, repo: InMemoryProjectRepository) -> Project:
    project = await repo.get(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"project {project_id} not found")
    return project


@router.post("", response_model=Project)
async def create_project(
    body: CreateProjectRequest,
    repo: InMemoryProjectRepository = Depends(get_repo),
) -> Project:
    return await repo.create(name=body.name)


@router.get("", response_model=list[Project])
async def list_projects(
    repo: InMemoryProjectRepository = Depends(get_repo),
) -> list[Project]:
    return await repo.list_all()


@router.get("/{project_id}", response_model=Project)
async def get_project(
    project_id: str, repo: InMemoryProjectRepository = Depends(get_repo)
) -> Project:
    return await _get_project_or_404(project_id, repo)


@router.post("/{project_id}/script", response_model=Project)
async def upload_script(
    project_id: str,
    body: UploadScriptRequest,
    repo: InMemoryProjectRepository = Depends(get_repo),
) -> Project:
    project = await _get_project_or_404(project_id, repo)
    if not body.content.strip():
        raise HTTPException(status_code=400, detail="script content must not be empty")
    project.script = body.content
    project.status = ProjectStatus.SCRIPT_UPLOADED
    return await repo.update(project)


@router.get("/{project_id}/script")
async def get_script(project_id: str, repo: InMemoryProjectRepository = Depends(get_repo)) -> dict:
    project = await _get_project_or_404(project_id, repo)
    return {"project_id": project.id, "content": project.script}


@router.post("/{project_id}/render", response_model=Project)
async def render_project(
    project_id: str, repo: InMemoryProjectRepository = Depends(get_repo)
) -> Project:
    """Runs the full M0 pipeline synchronously (fake plan -> fake resolve
    -> render). M4 replaces this with an async, resumable workflow run."""
    project = await _get_project_or_404(project_id, repo)
    if not project.script:
        raise HTTPException(status_code=400, detail="upload a script before rendering")
    return await run_pipeline(project, repo)


@router.get("/{project_id}/status")
async def get_status(project_id: str, repo: InMemoryProjectRepository = Depends(get_repo)) -> dict:
    project = await _get_project_or_404(project_id, repo)
    return {"project_id": project.id, "status": project.status, "error": project.error}


@router.get("/{project_id}/video")
async def get_video(
    project_id: str, repo: InMemoryProjectRepository = Depends(get_repo)
) -> FileResponse:
    project = await _get_project_or_404(project_id, repo)
    if not project.video_path:
        raise HTTPException(status_code=404, detail="no rendered video for this project yet")
    path = Path(project.video_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="rendered video file is missing on disk")
    return FileResponse(path, media_type="video/mp4", filename=f"{project_id}.mp4")


@router.delete("/{project_id}")
async def delete_project(
    project_id: str, repo: InMemoryProjectRepository = Depends(get_repo)
) -> dict:
    await _get_project_or_404(project_id, repo)
    # InMemoryProjectRepository has no delete in M0 (not needed for the
    # skeleton); real deletion arrives with the M2 repository.
    raise HTTPException(status_code=501, detail="project deletion lands in M2")
