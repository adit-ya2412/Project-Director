"""K10 — lexical pivot detection. Pure, no DB, no LLM."""

import re
from datetime import UTC, datetime

import pytest

from app.planners.fragments import split_narration_fragments
from app.schemas.timeline import (
    EmphasisDevice,
    EmphasisRegister,
    ProducedBy,
    Scene,
    Shot,
    ShotIntent,
    Timeline,
    TimelineStatus,
)
from app.timeline.pivot import attach_pivot_cue, detect_pivot


def _shot(
    shot_id: str,
    text: str,
    *,
    span: tuple[int, int] | None = None,
    order: int = 0,
    text_card: str | None = None,
) -> Shot:
    return Shot(
        id=shot_id,
        order=order,
        intent=ShotIntent.EXPLAIN,
        duration_s=2.0,
        narration_span=span if span is not None else (0, len(text)),
        text_card=text_card,
    )


def _timeline(text: str, *, shots: list[Shot] | None = None, extra_scenes: list[Scene] | None = None) -> Timeline:
    scene = Scene(
        id="sc_01",
        order=0,
        title="hook",
        narration_text=text,
        duration_s=2.0,
        shots=shots or [_shot("sh_01", text)],
    )
    scenes = [scene] + (extra_scenes or [])
    return Timeline(
        timeline_id="t1",
        project_id="p1",
        version=1,
        produced_by=ProducedBy.SHOT_PLANNER,
        status=TimelineStatus.DRAFT,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        scenes=scenes,
    )


def _fragment_index_for(text: str, token: str) -> int:
    pos = text.lower().find(token.lower())
    if pos < 0:
        pos = text.find(token)
    for fragment in split_narration_fragments(text):
        if fragment.start <= pos < fragment.end:
            return fragment.index
    raise AssertionError(f"{token!r} not inside any fragment of {text!r}")


@pytest.mark.parametrize(
    "text, expected_display",
    [
        ("har teesri SUV lekin kya Creta", "लेकिन"),
        ("yeh magar galat hai", "मगर"),
        ("every third SUV but is it special", "लेकिन"),
        ("हर तीसरी SUV लेकिन क्या Creta", "लेकिन"),
        ("यह मगर गलत है", "मगर"),
        ("Lekin kya Creta", "लेकिन"),
        ("BUT is it special", "लेकिन"),
    ],
)
def test_detects_pivot_tokens_case_insensitive(text: str, expected_display: str):
    hit = detect_pivot(_timeline(text))
    assert hit is not None
    assert hit.text == expected_display
    assert hit.text_register is EmphasisRegister.HI
    assert hit.shot_id == "sh_01"
    assert hit.anchor_fragment >= 1


def test_lekin_in_hinglish_has_the_correct_fragment_index():
    text = "har teesri SUV. lekin kya Creta special hai"
    hit = detect_pivot(_timeline(text))
    assert hit is not None
    assert hit.anchor_fragment == _fragment_index_for(text, "lekin")
    # Period split: "lekin" opens fragment 2, not the first sentence.
    assert hit.anchor_fragment == 2


def test_suv_like_string_detects_lekin():
    text = "2025 mein iske 2 lakh se zyada models bike. lekin kya Creta really that special"
    hit = detect_pivot(_timeline(text))
    assert hit is not None
    assert hit.matched.lower() == "lekin"
    assert hit.text == "लेकिन"
    assert hit.anchor_fragment == _fragment_index_for(text, "lekin")


@pytest.mark.parametrize(
    "text",
    [
        "press the button",
        "butter chicken",
        "",
        "no turn in this line",
        "button butter",
        # Latin suffix collision on the OTHER pivot token, correctly rejected.
        "magarmach ka shikar",
    ],
)
def test_non_matches(text: str):
    assert detect_pivot(_timeline(text)) is None


def test_first_of_two_wins():
    text = "lekin wait but also magar"
    hit = detect_pivot(_timeline(text))
    assert hit is not None
    assert hit.matched.lower() == "lekin"
    assert hit.text == "लेकिन"


def test_maps_onto_the_shot_whose_narration_span_covers_the_word():
    text = "first sentence. lekin the turn. leftover"
    lekin_at = text.find("lekin")
    shot_a = _shot("sh_a", text, span=(0, lekin_at), order=0)
    shot_b = _shot("sh_b", text, span=(lekin_at, len(text)), order=1)
    hit = detect_pivot(_timeline(text, shots=[shot_a, shot_b]))
    assert hit is not None
    assert hit.shot_id == "sh_b"
    assert hit.anchor_fragment == _fragment_index_for(text, "lekin")


def test_skips_when_no_shot_covers_the_span():
    text = "hello lekin there"
    # Span covers only "hello " — the pivot sits past the only shot.
    shot = _shot("sh_01", text, span=(0, 6))
    assert detect_pivot(_timeline(text, shots=[shot])) is None


def test_text_card_on_the_pivot_shot_means_the_reel_has_none():
    text = "hello lekin there. but later"
    shot = _shot("sh_01", text, text_card="TITLE")
    # First match is THE turn; we do not steal the card and we do not
    # fall through to `but`.
    assert detect_pivot(_timeline(text, shots=[shot])) is None


def test_attach_writes_the_canonical_cue_on_the_covering_shot():
    text = "bike. lekin kya Creta"
    original = _timeline(text)
    attached = attach_pivot_cue(original)
    assert original.all_shots()[0].emphasis_cue is None
    cue = attached.all_shots()[0].emphasis_cue
    assert cue is not None
    assert cue.device is EmphasisDevice.PIVOT
    assert cue.text == "लेकिन"
    assert cue.text_register is EmphasisRegister.HI
    assert cue.anchor_fragment == _fragment_index_for(text, "lekin")
    assert cue.offset_s == 0.0


def test_attach_is_noop_when_already_attached():
    text = "lekin now"
    first = attach_pivot_cue(_timeline(text))
    cue = first.all_shots()[0].emphasis_cue
    assert cue is not None
    second = attach_pivot_cue(first)
    assert second.all_shots()[0].emphasis_cue is not None
    assert second.all_shots()[0].emphasis_cue.anchor_fragment == cue.anchor_fragment
    assert second.all_shots()[0].emphasis_cue.text == cue.text
    # Input was not mutated into a second object.
    assert first.all_shots()[0].emphasis_cue is cue


def test_attach_is_noop_when_there_is_no_pivot_word():
    attached = attach_pivot_cue(_timeline("nothing to turn on"))
    assert attached.all_shots()[0].emphasis_cue is None


def test_devanagari_matra_after_a_pivot_token_still_matches():
    """KNOWN GAP in `\\b`, pinned deliberately (K10 review).

    `\\b` protects Latin properly - `button` / `butter` / `magarmach` are
    all rejected (see `test_non_matches`) - because every Latin letter is
    `\\w`. Devanagari BASE letters are `\\w` too, so the same protection
    holds for a following base consonant: `लेकिनक` is rejected.

    Devanagari COMBINING MARKS are not `\\w`. So a `\\b` fires between a
    consonant and a following matra or virama, and the pivot regex
    matches INSIDE a longer string.

    This test does NOT want that fixed. `लेकिनी` is not a Hindi
    word, so nothing real is misdetected today, and tightening the
    matching rule is a design decision outside K10. Its job is to make
    the asymmetry visible and impossible to change silently - and to
    fail loudly if the pivot token list is ever extended to words that
    take inflection, where an inflected form WOULD match on its stem.
    """
    # The Unicode facts underneath, asserted rather than described.
    assert "न".isalnum() is True  # U+0928 DEVANAGARI LETTER NA, category Lo
    assert re.fullmatch(r"\w", "न") is not None
    for mark in ("े", "ि", "्"):  # Mn, Mc, Mn
        assert mark.isalnum() is False
        assert re.fullmatch(r"\w", mark) is None

    # Consequence: the trailing `\b` closes on the mark, so these match.
    for text in ("लेकिनी", "मगरे", "लेकिन्क"):
        hit = detect_pivot(_timeline(text))
        assert hit is not None, text
        assert hit.matched in {"लेकिन", "मगर"}, text

    # A following BASE letter IS `\w`, so that half is genuinely
    # protected - the same way `butter` is.
    assert detect_pivot(_timeline("लेकिनक")) is None
    assert detect_pivot(_timeline("मगरक")) is None
