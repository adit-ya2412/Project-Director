import pytest

from app.core.config import settings


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    """Every test gets its own storage root so runs never collide and
    never leave files behind in the working tree."""
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    yield tmp_path
