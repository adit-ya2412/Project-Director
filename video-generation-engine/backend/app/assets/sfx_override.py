"""C3f SFX override/disable (analysis.md, decision 4): the pure core of
`POST /projects/{id}/sfx/{kind}/override`.

The endpoint owns I/O (ffprobe validation, hashing, bytes on disk,
`append_version`); this module owns the LIST algebra on
`sfx_plan.clips` - kept pure and separate so it is trivially
unit-testable and the endpoint stays a thin shell, mirroring how
`music_upload_warnings` sits beside the BGM upload endpoint."""

from app.schemas.timeline import SfxClipSelection, SfxKind


def apply_sfx_clip_override(
    clips: list[SfxClipSelection],
    kind: SfxKind,
    replacement: SfxClipSelection | None,
) -> list[SfxClipSelection]:
    """Return a NEW list with every clip of `kind` removed, then
    `replacement` appended when given (`None` = disable the kind: the
    renderer's `by_kind.get(kind)` miss already skips a missing kind, so
    removal IS disable - decision 4, at zero render cost).

    Never mutates the input list (I3: transforms build new state, they do
    not edit history in place). Order of surviving clips is preserved -
    rendering keys off `kind`, never position, but determinism is cheap."""
    kept = [clip for clip in clips if clip.kind != kind]
    if replacement is not None:
        kept.append(replacement)
    return kept
