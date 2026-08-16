"""FastAPI app factory. Wiring only — no business logic lives here
(implementation guide, api/ layer responsibility)."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.projects import router as projects_router
from app.core.config import settings
from app.core.logging import configure_logging, get_logger

# frontend/dist, built via `npm run build`. Not present in a backend-only
# dev checkout, so the mount below is skipped rather than crashing.
_FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"

configure_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Repositories are constructed per-request via DI (app/api/deps.py) -
    # nothing to hold on app.state.
    logger.info("app.startup", extra={"dry_run": settings.dry_run})
    yield
    logger.info("app.shutdown")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Video Generation Engine",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok", "dry_run": settings.dry_run}

    app.include_router(projects_router, prefix=settings.api_base_path)

    if _FRONTEND_DIST.is_dir():
        # Hashed build assets (JS/CSS) — vite emits these under /assets
        # with content-hashed names, so they're safe to cache aggressively;
        # StaticFiles' default caching headers are fine as-is.
        app.mount(
            "/assets", StaticFiles(directory=_FRONTEND_DIST / "assets"), name="frontend-assets"
        )

        index_html = _FRONTEND_DIST / "index.html"

        # Catch-all, registered last so `/health` and the API router above
        # always win first. `StaticFiles(html=True)` was tried here first
        # and doesn't actually do this - it only serves `index.html` for a
        # request that resolves to a directory, not for an arbitrary
        # client-side route - so a hard refresh on e.g.
        # `/projects/{id}/review` 404'd (verified live, not assumed). This
        # serves the matching file for anything that IS a real file under
        # dist/ (favicon.svg, etc.) and falls back to `index.html` -
        # letting React Router's client-side routing resolve - for
        # everything else.
        @app.get("/{full_path:path}", include_in_schema=False)
        async def serve_frontend(full_path: str) -> FileResponse:
            candidate = _FRONTEND_DIST / full_path
            if full_path and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(index_html)

    return app


app = create_app()
