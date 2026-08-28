"""OQ-2 focal sidecar — pure filesystem, no DB / no vision call."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.assets.focal import (
    DEFAULT_FOCAL,
    FOCAL_SOURCE_FALLBACK,
    FOCAL_SOURCE_VISION,
    format_focal_fingerprint,
    persist_vision_focal,
    read_focal_sidecar,
    resolve_shot_focals,
    write_focal_sidecar,
)
from app.providers.base import DepictionVerdict, SubjectFocal


def test_sidecar_round_trip(tmp_path: Path):
    write_focal_sidecar(
        tmp_path, "abc123", focal_x=0.2, focal_y=0.8, source=FOCAL_SOURCE_VISION
    )
    assert read_focal_sidecar(tmp_path, "abc123") == (0.2, 0.8)


def test_missing_sidecar_returns_none(tmp_path: Path):
    assert read_focal_sidecar(tmp_path, "nope") is None


def test_persist_invalid_writes_centre_fallback(tmp_path: Path):
    result = persist_vision_focal(tmp_path, "h1", focal_x=None, focal_y=0.3, shot_id="sh_01")
    assert result == DEFAULT_FOCAL
    assert read_focal_sidecar(tmp_path, "h1") == DEFAULT_FOCAL
    raw = (tmp_path / "h1.focal.json").read_text(encoding="utf-8")
    assert FOCAL_SOURCE_FALLBACK in raw


def test_persist_vision_coords(tmp_path: Path):
    result = persist_vision_focal(tmp_path, "h2", focal_x=0.25, focal_y=0.75)
    assert result == (0.25, 0.75)
    raw = (tmp_path / "h2.focal.json").read_text(encoding="utf-8")
    assert FOCAL_SOURCE_VISION in raw


def test_resolve_logs_fallback_for_missing(tmp_path: Path):
    write_focal_sidecar(tmp_path, "have", focal_x=0.1, focal_y=0.9, source=FOCAL_SOURCE_VISION)
    out = resolve_shot_focals(
        shot_ids=["sh_a", "sh_b", "sh_c"],
        content_hashes={"sh_a": "have", "sh_b": "missing"},
        assets_dir=tmp_path,
    )
    assert out["sh_a"] == (0.1, 0.9)
    assert out["sh_b"] is None
    assert out["sh_c"] is None  # no content hash


def test_fingerprint_format_empty_when_unresolved():
    assert format_focal_fingerprint(None) == ""
    assert format_focal_fingerprint((0.2, 0.8)) == "0.200000,0.800000"


def test_nan_sidecar_falls_back_to_unresolved(tmp_path: Path):
    """RV-Q5: json.loads accepts NaN; clamp_unit(nan) was 1.0 (frame corner)."""
    path = tmp_path / "bad.focal.json"
    path.write_text('{"focal_x": NaN, "focal_y": 0.5}', encoding="utf-8")
    from app.assets.focal import read_focal_sidecar

    assert read_focal_sidecar(tmp_path, "bad") is None


def test_depiction_verdict_no_longer_carries_focal():
    """The inverse of the test this replaces (output_quality_pass.md §14).

    `focal_x`/`focal_y` used to live on `DepictionVerdict` with defaults
    of 0.5, so a model that ignored the location question produced a
    confident centre that was written to disk as `focal_source="vision"`.
    Measured on a real backfill: 11 of 12 sidecars were exactly
    (0.50, 0.50). Location moved to `SubjectFocal`, which has NO
    defaults, so an unanswered question raises instead."""
    v = DepictionVerdict(confidently_wrong=False, reason="ok")
    assert not hasattr(v, "focal_x")
    assert not hasattr(v, "focal_y")

    with pytest.raises(ValidationError):
        SubjectFocal(subject="a driver", subject_location_words="upper left")

    ok = SubjectFocal(
        subject="a driver", subject_location_words="upper left", focal_x=0.3, focal_y=0.2
    )
    assert (ok.focal_x, ok.focal_y) == (0.3, 0.2)

    with pytest.raises(ValidationError):
        SubjectFocal(subject="x", subject_location_words="y", focal_x=1.4, focal_y=0.2)
