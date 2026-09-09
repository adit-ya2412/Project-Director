"""Lexical pivot detection (retention_fast_kinetic_text.md K10).

Retention scripts are built around the turn. v1 finds that turn by
token, not by meaning: `lekin` / `magar` / `but` and their Devanagari
spellings, first match in film order, one per reel. Pure — no DB, no
LLM, no seconds. The cue it attaches names a fragment INDEX; K2
resolves that to `offset_s` once real alignment exists.

Word-boundary matching is load-bearing: `button` / `butter` must not
fire. It is not symmetric across the two scripts, though - see the
`_PIVOT_RE` comment for the Devanagari combining-mark gap it does NOT
close. Canonical on-screen text and `text_register` are a fixed table
(pivot is Devanagari), not a planner choice.
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
#
# What `\b` actually buys here, measured (K10 review): Devanagari BASE
# letters ARE `\w` - न U+0928 is category Lo, `isalnum()` True - so
# `\b` does protect against the Latin-style collision in both scripts:
# `button`, `butter`, `magarmach` and `लेकिनक` (lekin + base क) are all
# correctly rejected today.
#
# Combining marks are NOT `\w`, though: े U+0947 (Mn), ि U+093F (Mc)
# and the virama ् U+094D (Mn) all report `isalnum() == False`. A `\b`
# therefore FIRES between a consonant and a following matra, so this
# regex matches INSIDE `लेकिनी` and `मगरे` - a pivot token plus a vowel
# sign or virama still reads as a whole-word hit. Deliberately NOT
# fixed: neither is a real Hindi word, so the risk today is nil, and
# changing the matching rule (a trailing `(?![\u0900-\u097F])`
# lookahead, say) is a design decision, not a bug fix. The risk GROWS
# the moment this token list is extended to words that TAKE
# INFLECTION, since an inflected form would then match on its bare
# stem. Pinned by `tests/unit/timeline/test_pivot.py::
# test_devanagari_matra_after_a_pivot_token_still_matches`.
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
    text_register: EmphasisRegister
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
            text_register=EmphasisRegister.HI,
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
                text_register=hit.text_register,
            )
            return copy
    return copy
