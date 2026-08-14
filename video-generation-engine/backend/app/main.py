"""FastAPI app factory. Wiring only — no business logic lives here
(implementation guide, api/ layer responsibility)."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.projects import router as projects_router
from app.core.config import settings
from app.core.logging import configure_logging, get_logger

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

    return app


app = create_app()
