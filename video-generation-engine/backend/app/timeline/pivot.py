"""Lexical pivot detection (retention_fast_kinetic_text.md K10).

Retention scripts are built around the turn. v1 finds that turn by
token, not by meaning: `lekin` / `magar` / `but` and their Devanagari
spellings, first match in film order, one per reel. Pure — no DB, no
LLM, no seconds. The cue it attaches names a fragment INDEX; K2
resolves that to `offset_s` once real alignment exists.

Word-boundary matching is load-bearing: `button` / `butter` must not
fire. Canonical on-screen text and register are a fixed table (pivot
is Devanagari), not a planner choice.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.core.logging import get_logger
from app.planners.fragments import split_narration_fragments
from app.schemas.timeline import (
    EmphasisCue,
    EmphasisDevice,
    EmphasisRegister,
    Shot,
    Timeline,
)

logger = get_logger(__name__)

# Longer Latin tokens first so a future addition cannot shadow them.
# Devanagari letters are `\w` in Python 3, so `\b` holds for both scripts.
_PIVOT_RE = re.compile(
    r"\b(?:lekin|magar|but|लेकिन|मगर)\b",
    re.IGNORECASE | re.UNICODE,
)

# Role table: pivot is Devanagari. `but` maps onto the same beat as `lekin`.
_CANONICAL_TEXT = {
    "lekin": "लेकिन",
    "लेकिन": "लेकिन",
    "but": "लेकिन",
    "magar": "मगर",
    "मगर": "मगर",
}


@dataclass(frozen=True)
class PivotHit:
    """Enough to build an `EmphasisCue` without inventing a shot."""

    scene_id: str
    shot_id: str
    anchor_fragment: int
    text: str
    register: EmphasisRegister
    matched: str


def _canonical_display(matched: str) -> str:
    return _CANONICAL_TEXT[matched.lower()]


def _covering_shot(scene_shots: list[Shot], char_index: int) -> Shot | None:
    for shot in scene_shots:
        if shot.narration_span is None:
            continue
        start, end = shot.narration_span
        if start <= char_index < end:
            return shot
    return None


def _anchor_fragment(narration_text: str, char_index: int) -> int | None:
    for fragment in split_narration_fragments(narration_text):
        if fragment.start <= char_index < fragment.end:
            return fragment.index
    return None


def detect_pivot(timeline: Timeline) -> PivotHit | None:
    """First pivot token in film order, or None.

    Skips a match whose covering shot is missing (do not invent a shot)
    or already carries a non-empty `text_card` (K3 mutual exclusion).
    That skipped match is still THE turn — v1 does not search further,
    so a text_card on the pivot shot means the reel has no pivot.
    """
    for scene in sorted(timeline.scenes, key=lambda s: s.order):
        text = scene.narration_text or ""
        match = _PIVOT_RE.search(text)
        if match is None:
            continue
        char_index = match.start()
        shot = _covering_shot(sorted(scene.shots, key=lambda s: s.order), char_index)
        if shot is None:
            logger.info(
                "pivot.skipped_no_covering_shot",
                extra={
                    "scene_id": scene.id,
                    "matched": match.group(0),
                    "char_index": char_index,
                },
            )
            return None
        if shot.text_card:
            logger.info(
                "pivot.skipped_text_card",
                extra={
                    "scene_id": scene.id,
                    "shot_id": shot.id,
                    "matched": match.group(0),
                },
            )
            return None
        fragment_index = _anchor_fragment(text, char_index)
        if fragment_index is None:
            logger.info(
                "pivot.skipped_no_fragment",
                extra={
                    "scene_id": scene.id,
                    "shot_id": shot.id,
                    "char_index": char_index,
                },
            )
            return None
        matched = match.group(0)
        return PivotHit(
            scene_id=scene.id,
            shot_id=shot.id,
            anchor_fragment=fragment_index,
            text=_canonical_display(matched),
            register=EmphasisRegister.HI,
            matched=matched,
        )
    return None


def attach_pivot_cue(timeline: Timeline) -> Timeline:
    """Return a copy with `emphasis_cue` set on the matching shot.

    No-op (still a copy) when there is no attachable hit or a pivot cue
    is already present. Never mutates `timeline` in place.
    """
    copy = timeline.model_copy(deep=True)
    if any(
        shot.emphasis_cue is not None and shot.emphasis_cue.device is EmphasisDevice.PIVOT
        for shot in copy.all_shots()
    ):
        return copy
    hit = detect_pivot(copy)
    if hit is None:
        return copy
    for scene in copy.scenes:
        for shot in scene.shots:
            if shot.id != hit.shot_id:
                continue
            if shot.text_card:
                return copy
            shot.emphasis_cue = EmphasisCue(
                device=EmphasisDevice.PIVOT,
                anchor_fragment=hit.anchor_fragment,
                text=hit.text,
                register=hit.register,
            )
            return copy
    return copy
