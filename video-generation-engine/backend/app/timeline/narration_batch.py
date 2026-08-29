"""RV-Q10: batch contiguous scenes into one TTS request, then split.

`narration_fit` and the render mux both assume one alignment + one audio
file per scene, indexed by `Shot.narration_span` into that scene's own
`narration_text`. This module does not change that contract. It only
decides *which scenes share a provider call* and how to carve the
returned alignment back into per-scene pieces. (The audio file itself is
`.mp3` for a scene synthesised alone and `.wav` for one carved out of a
batch - see `app.renderer.narration_slice` and
`app.workflow.steps.narration._persist_slice` - but that split lives
entirely in the workflow step; this module only produces the per-scene
alignment and the `[start, end)` window to cut.)

A cached content-hash is never overwritten (the hash keys the request,
not the bytes; two projects sharing a scene's text must keep the first
writer's audio). A cache hit in the middle of a timeline therefore
breaks the batch. Duplicate texts in the same timeline still unique-by-
hash: the first miss is synthesised, later copies reuse that slice and
do not break a run of surrounding misses.

The joiner is a single newline so ElevenLabs has a pause to land on,
matching how this codebase already treats `\n` as a spoken rest. The
joiner is excluded from each scene's alignment (spans would not survive
otherwise) and absorbed into the previous scene's last-character end
time so shot durations and sliced audio stay the same length.

## RV-Q13 — editing one scene un-does this feature for that scene

`scripts/edit_narration_text.py` changes one scene's `narration_text`,
which changes its content hash, which makes it the ONLY cache miss in
an otherwise-fully-cached timeline. `plan_tts_batches` correctly refuses
to batch a lone miss with anything (there is nothing uncached next to
it to batch with - its cached neighbours are, by definition, not in
`ordered_members` as misses), so it is synthesised ALONE, with a fresh
ElevenLabs performance, while its neighbours keep their original batched
audio. That reproduces, for exactly the scene a human just asked to
fix, the very voice-character discontinuity at scene joins this feature
exists to remove. Not a bug in this module - `plan_tts_batches` is doing
the only safe thing it can with the inputs it is given - but a real gap
in the feature. The honest fix is not here: it is re-batching the
edited scene together with its still-cached neighbours, which means
deliberately discarding those neighbours' cached audio and re-paying for
it. Nothing in this module or `edit_narration_text.py` does that today.
"""

from __future__ import annotations

from collections.abc import Sequence, Set
from dataclasses import dataclass

from app.core.errors import PermanentError

NARRATION_BATCH_JOINER = "\n"


@dataclass(frozen=True)
class NarrationBatchMember:
    scene_id: str
    content_hash: str
    text: str


@dataclass(frozen=True)
class SceneNarrationSlice:
    """One scene's share of a batched TTS response.

    `alignment` characters equal `list(text)` and times are rebased so
    the slice's audio starts at t=0. `audio_start_s`/`audio_end_s` are
    absolute times in the batched audio, for the ffmpeg cut.
    """

    scene_id: str
    content_hash: str
    text: str
    alignment: dict
    audio_start_s: float
    audio_end_s: float


def join_batch_text(
    members: Sequence[NarrationBatchMember],
    joiner: str = NARRATION_BATCH_JOINER,
) -> str:
    return joiner.join(member.text for member in members)


def plan_tts_batches(
    members: Sequence[NarrationBatchMember],
    *,
    cached_hashes: Set[str],
    max_characters: int,
    joiner: str = NARRATION_BATCH_JOINER,
) -> list[list[NarrationBatchMember]]:
    """Pack contiguous unique-hash misses into TTS requests.

    A member whose hash is already cached flushes the current batch
    (the cached audio cannot share a performance with its neighbours).
    A member whose hash is already queued in this walk is skipped
    without flushing — unique-by-hash, and a later distinct miss may
    still ride with the earlier one.

    A single member longer than `max_characters` is still emitted as
    its own batch; the API, not this planner, rejects oversized scenes
    (same as the pre-RV-Q10 per-scene path).
    """
    batches: list[list[NarrationBatchMember]] = []
    current: list[NarrationBatchMember] = []
    current_len = 0
    queued: set[str] = set()

    def flush() -> None:
        nonlocal current, current_len
        if current:
            batches.append(current)
            current = []
            current_len = 0

    for member in members:
        if member.content_hash in cached_hashes:
            flush()
            continue
        if member.content_hash in queued:
            continue
        extra = len(member.text) + (len(joiner) if current else 0)
        if current and current_len + extra > max_characters:
            flush()
            extra = len(member.text)
        current.append(member)
        queued.add(member.content_hash)
        current_len += extra
    flush()
    return batches


def split_batched_alignment(
    alignment: dict,
    members: Sequence[NarrationBatchMember],
    *,
    joiner: str = NARRATION_BATCH_JOINER,
    audio_duration_s: float | None = None,
) -> list[SceneNarrationSlice]:
    """Carve one batched `/with-timestamps` alignment into per-scene slices.

    Requires the raw (non-normalized) character arrays to equal the
    joined request text, the same 1:1 contract `Shot.narration_span`
    already depends on. The joiner characters are skipped. Each scene
    except the last has its last-character end stretched to the next
    scene's first-character start so the following newline pause is
    attributed to the scene that is still on screen — otherwise the
    muxed audio would be longer than `narration_fit`'s shot durations
    by one pause per join.
    """
    if not members:
        return []
    empty = next((m for m in members if len(m.text) == 0), None)
    if empty is not None:
        raise PermanentError(
            f"scene {empty.scene_id} has empty narration_text; cannot slice a "
            "batched alignment into an empty span"
        )
    try:
        chars = list(alignment["characters"])
        starts = [float(t) for t in alignment["character_start_times_seconds"]]
        ends = [float(t) for t in alignment["character_end_times_seconds"]]
    except (KeyError, TypeError, ValueError) as exc:
        raise PermanentError(f"malformed batched narration alignment: {exc}") from exc
    if not (len(chars) == len(starts) == len(ends)):
        raise PermanentError(
            "malformed batched narration alignment: parallel arrays differ in length "
            f"(characters={len(chars)}, starts={len(starts)}, ends={len(ends)})"
        )

    expected = join_batch_text(members, joiner)
    got = "".join(chars)
    if got != expected:
        raise PermanentError(
            "batched alignment does not match the joined request text "
            f"(alignment {len(got)} chars, request {len(expected)} chars)"
        )

    slices: list[SceneNarrationSlice] = []
    cursor = 0
    n_members = len(members)
    for index, member in enumerate(members):
        n = len(member.text)
        piece_chars = chars[cursor : cursor + n]
        piece_starts = starts[cursor : cursor + n]
        piece_ends = ends[cursor : cursor + n]
        first_abs = piece_starts[0]
        last_abs = piece_ends[-1]
        is_last = index + 1 == n_members
        if is_last:
            audio_start = 0.0 if index == 0 else first_abs
            if audio_duration_s is not None and audio_duration_s >= last_abs:
                audio_end = audio_duration_s
            else:
                audio_end = last_abs
            last_end_abs = last_abs
        else:
            next_cursor = cursor + n + len(joiner)
            if next_cursor >= len(starts):
                raise PermanentError(
                    f"batched alignment ended before scene {members[index + 1].scene_id}"
                )
            next_first = starts[next_cursor]
            if next_first < last_abs:
                raise PermanentError(
                    f"scene {member.scene_id} overlaps the next scene in the batched "
                    f"alignment ({last_abs:.3f}s > {next_first:.3f}s)"
                )
            audio_start = 0.0 if index == 0 else first_abs
            audio_end = next_first
            last_end_abs = next_first
        if audio_end <= audio_start:
            raise PermanentError(
                f"scene {member.scene_id} sliced to a non-positive audio window "
                f"({audio_start:.3f}s .. {audio_end:.3f}s)"
            )
        rebased_starts = [t - audio_start for t in piece_starts]
        rebased_ends = [t - audio_start for t in piece_ends]
        rebased_ends[-1] = last_end_abs - audio_start
        slices.append(
            SceneNarrationSlice(
                scene_id=member.scene_id,
                content_hash=member.content_hash,
                text=member.text,
                alignment={
                    "characters": piece_chars,
                    "character_start_times_seconds": rebased_starts,
                    "character_end_times_seconds": rebased_ends,
                },
                audio_start_s=audio_start,
                audio_end_s=audio_end,
            )
        )
        cursor += n
        if not is_last:
            cursor += len(joiner)
    return slices
