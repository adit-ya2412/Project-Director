"""C3f (analysis.md, decision 4): pure list algebra of
`apply_sfx_clip_override` - the core of the per-kind SFX
override/disable endpoint. Pure functions, no DB/ffmpeg - safe to run
with `--noconftest` (see the RV3 conftest gate)."""

from app.assets.sfx_override import apply_sfx_clip_override
from app.schemas.timeline import SfxClipSelection, SfxKind


def _clip(kind: SfxKind, source_id: str) -> SfxClipSelection:
    return SfxClipSelection(
        kind=kind,
        provider="local",
        track_id=f"{source_id}.mp3",
        source_url=f"http://example.test/{source_id}",
        licence="cc0",
        attribution=source_id,
        content_hash=f"hash-{source_id}",
    )


def _plan() -> list[SfxClipSelection]:
    return [
        _clip(SfxKind.WHOOSH, "whoosh_a"),
        _clip(SfxKind.STINGER, "stinger_a"),
        _clip(SfxKind.TRANSITION, "transition_a"),
    ]


def test_replacing_a_kind_preserves_the_other_clips():
    replacement = _clip(SfxKind.WHOOSH, "whoosh_custom")
    result = apply_sfx_clip_override(_plan(), SfxKind.WHOOSH, replacement)
    assert [c.track_id for c in result] == [
        "stinger_a.mp3",
        "transition_a.mp3",
        "whoosh_custom.mp3",
    ]


def test_replacing_adds_the_kind_when_it_had_no_clip():
    """A kind disabled earlier can be re-enabled by uploading a file."""
    result = apply_sfx_clip_override(_plan(), SfxKind.WHOOSH, None)
    re_enabled = apply_sfx_clip_override(
        result, SfxKind.WHOOSH, _clip(SfxKind.WHOOSH, "whoosh_new")
    )
    assert any(c.kind == SfxKind.WHOOSH for c in re_enabled)
    assert len(re_enabled) == 3


def test_disable_removes_only_that_kinds_clips():
    result = apply_sfx_clip_override(_plan(), SfxKind.WHOOSH, None)
    kinds = {c.kind for c in result}
    assert SfxKind.WHOOSH not in kinds
    assert {SfxKind.STINGER, SfxKind.TRANSITION} == kinds


def test_disabling_an_absent_kind_is_a_no_op():
    plan = _plan()
    result = apply_sfx_clip_override(plan, SfxKind.WHOOSH, None)
    again = apply_sfx_clip_override(result, SfxKind.WHOOSH, None)
    assert [c.content_hash for c in again] == [c.content_hash for c in result]


def test_all_duplicates_of_a_kind_are_removed_on_replace():
    """Defensive: `by_kind = {clip.kind: clip ...}` renders only one clip
    per kind anyway, but the stored palette must not keep stale
    duplicates of an overridden kind."""
    plan = [
        _clip(SfxKind.WHOOSH, "whoosh_a"),
        _clip(SfxKind.WHOOSH, "whoosh_b"),
        _clip(SfxKind.STINGER, "stinger_a"),
    ]
    result = apply_sfx_clip_override(plan, SfxKind.WHOOSH, _clip(SfxKind.WHOOSH, "whoosh_custom"))
    whooshes = [c for c in result if c.kind == SfxKind.WHOOSH]
    assert [c.track_id for c in whooshes] == ["whoosh_custom.mp3"]
    assert len(result) == 2


def test_input_list_is_never_mutated():
    """I3: transforms build new state - the caller's list (the previous
    version's document) must survive untouched."""
    plan = _plan()
    snapshot = [c.content_hash for c in plan]
    apply_sfx_clip_override(plan, SfxKind.WHOOSH, None)
    assert [c.content_hash for c in plan] == snapshot
