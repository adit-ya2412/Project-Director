"""Async engine construction.

`settings.database_url` wins if set; otherwise it is built from the
individual `postgres_*` settings (matches .env.example's documented
override behaviour).
"""

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings


def resolve_database_url() -> str:
    if settings.database_url:
        return settings.database_url
    return (
        f"postgresql+asyncpg://{settings.postgres_user}:{settings.postgres_password}"
        f"@{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}"
    )


def create_engine() -> AsyncEngine:
    # NullPool: every checkout is a brand-new asyncpg connection, never
    # reused across event loops. Simplest correct option while both the
    # sync TestClient (its own portal thread + loop) and pytest-asyncio
    # fixtures (a fresh loop per test) can end up touching this engine.
    # Revisit with real pooling once there's load to justify it
    # (Principle 18, simple first).
    return create_async_engine(resolve_database_url(), poolclass=NullPool)


engine: AsyncEngine = create_engine()
