"""Pure-function safety net for `resolve_project_storage_dir`
(`app/projects/deletion.py`) - the one check that stands between a
`project_id` string and `shutil.rmtree`. No Postgres, no async - safe
under `--noconftest` and under an ad-hoc `pytest tests/unit` run (same
idiom as `test_focal_override_api.py`'s own docstring).

`settings.storage_root` is already pointed at `tmp_path` by the
top-level `isolated_storage` autouse fixture (`tests/conftest.py`) - no
extra monkeypatching needed here.
"""

import uuid

import pytest

from app.core.config import settings
from app.projects.deletion import resolve_project_storage_dir


def test_a_real_project_id_resolves_inside_storage_root(tmp_path):
    project_id = str(uuid.uuid4())
    resolved = resolve_project_storage_dir(project_id)
    assert resolved == (tmp_path / project_id).resolve()
    assert resolved.is_relative_to(settings.storage_root.resolve())


def test_dot_dot_traversal_is_refused(tmp_path):
    with pytest.raises(RuntimeError):
        resolve_project_storage_dir("../outside")


def test_absolute_path_project_id_is_refused(tmp_path):
    # `Path("./storage") / "/some/absolute/path"` does not APPEND the
    # second operand - an absolute right-hand side replaces the left
    # entirely (verified: `(root / str(outside)).resolve() == outside`,
    # not `root / outside`). A naive `str(candidate).startswith(str(root))`
    # check would still catch this by luck; resolving both sides and
    # using `is_relative_to` catches it for the right reason.
    outside = tmp_path.parent / "definitely-outside"
    with pytest.raises(RuntimeError):
        resolve_project_storage_dir(str(outside))


def test_empty_project_id_refuses_to_return_the_storage_root_itself(tmp_path):
    # storage_root / "" == storage_root - refusing this specifically
    # stops a caller from ever being handed the ENTIRE storage tree to
    # remove, not just one project's slice of it.
    with pytest.raises(RuntimeError):
        resolve_project_storage_dir("")


def test_two_different_real_uuids_never_collide(tmp_path):
    a = resolve_project_storage_dir(str(uuid.uuid4()))
    b = resolve_project_storage_dir(str(uuid.uuid4()))
    assert a != b
