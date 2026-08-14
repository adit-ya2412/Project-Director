import pytest
import pytest_asyncio
from sqlalchemy import text

import app.models  # noqa: F401 - registers every model on Base.metadata
from app.core.config import settings
from app.db.base import Base
from app.db.database import engine


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    """Every test gets its own storage root so runs never collide and
    never leave files behind in the working tree."""
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    yield tmp_path


@pytest_asyncio.fixture(autouse=True)
async def clean_database():
    """Truncate every application table before each test so tests never
    see another test's rows. Runs against the real Postgres started via
    `docker compose up -d postgres` (M2) - there is no separate mocked
    database for integration/e2e tests (docs/12_Testing_Strategy.md)."""
    tables = [t.name for t in Base.metadata.sorted_tables]
    if not tables:
        # Without the `import app.models` above, no model module is imported
        # when a single unit-test file runs in isolation, `sorted_tables` is
        # empty, and the TRUNCATE below becomes `TRUNCATE TABLE  RESTART
        # IDENTITY CASCADE` - a syntax error that surfaces as six confusing
        # setup errors rather than "you forgot to register the models".
        raise RuntimeError(
            "no tables registered on Base.metadata - app.models was not imported"
        )
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE TABLE {', '.join(tables)} RESTART IDENTITY CASCADE"))
    yield
