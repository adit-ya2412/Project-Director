"""K15: the stamp fits its phrase on ONE line, or it is not a stamp.

No Chromium here, and these tests cannot see a wrap — that is the whole
lesson of K14.5, whose word-timing tests were green while every phrase
on screen was broken. What they CAN pin is the arithmetic the render
depends on: that the width estimate never falls under what Chromium
actually drew (measured through real frames in `tmp/k15/`, numbers
quoted below), that the fitted font always fits inside the usable band,
that the Devanagari path uses the wght=700 instance the stamp is drawn
at, and that a single-word stamp is byte-identical to what shipped
before the fix.

Layout proof lives in the rendered frames, not here. `tmp/k15/
verify_k15_stamp_fit.py` renders the five cases through real Chromium
and measures ink box against band box; the work log records the
numbers.
"""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.renderer.compositor import (
    _STAMP_MIN_PUNCH_FONT,
    _STAMP_REF_FONT,
    _STAMP_SLAB_INSETS,
    EMPHASIS_FONT_PATH,
    OverlayCue,
    collect_emphasis_overlay_cues,
    emphasis_cue_content_hash,
    overlay_input_hash,
    stamp_band,
    stamp_text_width,
)
from app.schemas.timeline import (
    EmphasisCue,
    EmphasisDevice,
    EmphasisPalette,
    EmphasisRegister,
    ProducedBy,
    Scene,
    Shot,
    ShotIntent,
    Timeline,
    TimelineMetadata,
    TimelineStatus,
)

W, H = 720, 1280
USABLE = 664  # 720 - 4*14, the slab's own content box


def _usable(canvas_width: int = W, canvas_height: int = H) -> int:
    band = stamp_band(canvas_width, canvas_height)
    assert band is not None
    return band.width - _STAMP_SLAB_INSETS * band.pad


# ---------------------------------------------------------------- control


SINGLE_WORDS = [
    ("2025", "en"),  # the shipped stamp of the SUV spike / K11 verification
    ("Parts", "en"),
    ("Year", "en"),
    ("3rd", "en"),
    ("लेकिन", "hi"),
    ("ज़्यादा", "hi"),  # nukta-bearing: the case the first table got wrong
    ("गाड़ी", "hi"),
    ("दो लाख", "hi"),  # two SHORT words: still fits at the reference font
]


@pytest.mark.parametrize("text,register", SINGLE_WORDS)
def test_a_word_that_fits_keeps_the_reference_font_and_props(text: str, register: str):
    """THE CONTROL. One word is the look every prior reel was judged on,
    so a stamp that fitted before K15 must resolve the identical
    rectangle — not merely a similar one. Rendered frames agree: the
    `Parts` PNG is byte-identical across the two Chromium runs either
    side of the change (`tmp/k15/before` vs `tmp/k15/after`, md5
    f12b10f0934439e96a9e95b461d034f6)."""
    plain = stamp_band(W, H)
    fitted = stamp_band(W, H, text=text, text_register=register)
    assert plain is not None and fitted is not None
    assert fitted.font_size == _STAMP_REF_FONT == 190
    assert fitted.as_props() == plain.as_props()
    assert fitted.hash_payload() == plain.hash_payload()
    assert (fitted.left, fitted.top, fitted.width, fitted.height) == (0, 320, 720, 218)


def test_single_word_stamp_misses_no_cache():
    """The props are the cache key and the render fingerprint, so
    'unchanged props' has to mean unchanged HASHES — otherwise every
    project re-renders its overlay for a fix that changed nothing about
    it."""
    before = OverlayCue(
        device="stamp",
        text="2025",
        text_register="en",
        offset_s=2.8,
        start_frame=84,
        end_frame=110,
        shot_id="s1",
        treatment="slab",
        band=stamp_band(W, H),  # the pre-K15 call: no text
    )
    after = OverlayCue(
        device="stamp",
        text="2025",
        text_register="en",
        offset_s=2.8,
        start_frame=84,
        end_frame=110,
        shot_id="s1",
        treatment="slab",
        band=stamp_band(W, H, text="2025", text_register="en"),
    )
    assert emphasis_cue_content_hash([before]) == emphasis_cue_content_hash([after])
    common = dict(
        width=W,
        height=H,
        fps=30,
        duration_in_frames=359,
        font_hash="deadbeef",
        palette=EmphasisPalette(accent="#FFC300", pivot_ground="#FF2E2E"),
    )
    assert overlay_input_hash(cues=[before], **common) == overlay_input_hash(
        cues=[after], **common
    )


# ------------------------------------------------------- the width model


# Drawn widths measured off real Chromium frames at 720x1280 on
# 2026-09-10 (`tmp/k15/verify_k15_stamp_fit.py`): the slab's outer box
# minus its 4*pad inset, i.e. the content box the type actually
# occupied, at the font size each phrase was fitted to.
#
#   text                 font   slab x        content px
#   Parts                 190   80..639        559 - 56 = 503
#   Tata Nexon             94   44..675        631 - 56 = 575
#   लाखों लोग              156   12..707        695 - 56 = 639
#   बिकने वाली SUV          93   17..702        685 - 56 = 629
#   EVERY 3rd SUV          69   52..667        615 - 56 = 559
#   service centre         73   56..663        607 - 56 = 551
MEASURED_DRAWN = [
    ("Parts", "en", 190, 503),
    ("Tata Nexon", "en", 94, 575),
    ("लाखों लोग", "hi", 156, 639),
    ("बिकने वाली SUV", "hi", 93, 629),
    ("EVERY 3rd SUV", "en", 69, 559),
    ("service centre", "en", 73, 551),
]


@pytest.mark.parametrize("text,register,font,drawn", MEASURED_DRAWN)
def test_width_estimate_never_falls_under_what_chromium_drew(
    text: str, register: str, font: int, drawn: int
):
    """The one direction that matters. An estimate BELOW the drawn width
    is the wrap coming back; above it is a slightly smaller glyph. The
    upper bound is loose on purpose (the estimate takes the wider of two
    Latin Black faces and rounds every advance up onto a 0.05 em grid)
    but it is bounded, so a change that makes the model wildly
    pessimistic — and the type needlessly tiny — fails here too."""
    estimate = stamp_text_width(text=text, text_register=register, font_size=font)
    assert estimate >= drawn, f"{text!r} underestimated: {estimate} < {drawn}"
    assert estimate <= round(drawn * 1.25), f"{text!r} wastes font size: {estimate}"


def test_devanagari_is_measured_at_the_bold_instance_not_the_default():
    """The trap K15 was warned about. `NotoSansDevanagari-Regular.ttf` is
    a variable font, `font.ts` declares weight 100-900 and `Stamp.tsx`
    draws 700, so the `hmtx` defaults (the wght=400 master) are 8-10%
    NARROW — exactly enough to put the wrap back. Re-measures the
    vendored file and fails if any baked ceiling has fallen below the
    real wght=700 advance."""
    instancer = pytest.importorskip(
        "fontTools.varLib.instancer",
        reason="fontTools is a dev-only tool; the advances are baked constants",
    )
    from fontTools.ttLib import TTFont

    bold = instancer.instantiateVariableFont(
        TTFont(EMPHASIS_FONT_PATH),
        {"wght": 700, "wdth": 100},
        inplace=False,
        updateFontNames=False,
    )
    upem = bold["head"].unitsPerEm
    cmap = bold.getBestCmap()
    hmtx = bold["hmtx"]
    checked = 0
    for text, register in [(t, r) for t, r, _, _ in MEASURED_DRAWN] + SINGLE_WORDS:
        if register != "hi":
            continue
        for char in text.replace(" ", ""):
            glyph = cmap.get(ord(char))
            if glyph is None:
                continue
            real_em = hmtx[glyph][0] / upem
            baked = stamp_text_width(text=char, text_register="hi", font_size=1000)
            assert baked >= real_em * 1000 - 1, (
                f"{char!r} baked {baked / 1000:.3f} em is under the wght=700 "
                f"advance {real_em:.3f} em"
            )
            checked += 1
    assert checked > 10


def test_hi_register_charges_latin_to_the_vendored_face_not_the_heavy_stack():
    """A `hi` stamp is drawn with the bundled Noto, whose cmap covers
    Basic Latin, so `SUV` inside a Devanagari phrase is Noto's `SUV` and
    not `Segoe UI Black`'s. Charging the heavy stack for it is a ~25%
    width error on the mixed-script case."""
    hi = stamp_text_width(text="SUV", text_register="hi", font_size=190)
    en = stamp_text_width(text="SUV", text_register="en", font_size=190)
    assert hi < en
    # And it is not silently the fallback ceiling for every glyph.
    assert hi < round(3 * 1.15 * 190)


def test_unknown_characters_are_charged_the_widest_glyph():
    """Erring wide on an unmapped character shrinks the type; erring
    narrow wraps it."""
    wide = stamp_text_width(text="字", text_register="en", font_size=100)
    assert wide == 114  # 1.10 em * 100 + 4px of tracking


def test_non_spacing_marks_cost_nothing():
    """The bug the first version of the table shipped: a nukta charged
    like a consonant made `ज़्यादा` measure 3.55 em against a real 2.57
    and shrank a word that fits at the reference font. Marks are read
    off the Unicode category now, so no bucket can claim one."""
    assert stamp_text_width(text="ज", text_register="hi", font_size=1000) == (
        stamp_text_width(text="ज़", text_register="hi", font_size=1000)
    )
    band = stamp_band(W, H, text="ज़्यादा", text_register="hi")
    assert band is not None
    assert band.font_size == _STAMP_REF_FONT


def test_a_single_word_wider_than_the_stack_shrinks_rather_than_breaking():
    """Not every single word fitted before K15, and this is the honest
    cost of taking the wider of the two Latin Black faces. `CRETA` at
    190 measures 638px in Segoe UI Black (fits the 664px content box)
    and 738px in Arial Black (does not), and Python cannot know which
    one Chromium will resolve. Taking the max sets it at 165 — 13%
    smaller than it needs to be on a Segoe host, against a slab 74px
    wider than the canvas on an Arial Black one, where the canvas
    itself would cut the outer letters. `MOST SOLD` overflows both
    faces and was always broken."""
    creta = stamp_band(W, H, text="CRETA", text_register="en")
    assert creta is not None
    assert creta.font_size == 165
    assert stamp_text_width(text="CRETA", text_register="en", font_size=190) > USABLE
    most = stamp_band(W, H, text="MOST SOLD", text_register="en")
    assert most is not None
    assert most.font_size < _STAMP_REF_FONT


# -------------------------------------------------------------- the fit


FITTED = [
    ("Tata Nexon", "en", 94),
    ("EVERY 3rd SUV", "en", 69),
    ("service centre", "en", 73),
    ("लाखों लोग", "hi", 156),
    ("बिकने वाली SUV", "hi", 93),
    ("सर्विस सेंटर", "hi", 134),
]


@pytest.mark.parametrize("text,register,expected", FITTED)
def test_fitted_font_size_is_pinned(text: str, register: str, expected: int):
    """These are the sizes the verification frames were rendered and
    looked at, so they are the numbers the look was judged on."""
    band = stamp_band(W, H, text=text, text_register=register)
    assert band is not None
    assert band.font_size == expected


PHRASES = [t for t, _, _ in FITTED] + [
    "HYUNDAI CRETA",
    "सबसे ज़्यादा बिकने वाली",
    "Punch vs Nexon vs Venue",
    "क्ष क्ष क्ष क्ष क्ष",
    "WWWWWWWWWWWWWWWWWWWW",
    "x" * 200,
]


@pytest.mark.parametrize("text", PHRASES)
@pytest.mark.parametrize("register", ["en", "hi"])
@pytest.mark.parametrize("canvas", [(720, 1280), (1080, 1920), (360, 640)])
def test_the_fitted_line_always_fits_inside_the_usable_band(
    text: str, register: str, canvas: tuple[int, int]
):
    """The invariant the whole change exists for: at the size the band
    reports, the estimated line is inside `band width - 4*pad`. A
    failure here is a phrase that reaches the slab edge, which is where
    CSS used to break it."""
    width, height = canvas
    band = stamp_band(width, height, text=text, text_register=register)
    assert band is not None
    usable = band.width - _STAMP_SLAB_INSETS * band.pad
    line = stamp_text_width(
        text=text, text_register=register, font_size=band.font_size
    )
    assert line <= usable or band.font_size == 1
    assert 1 <= band.font_size <= round(_STAMP_REF_FONT * (width / W))


def test_the_font_only_ever_shrinks():
    """No phrase is ever set LARGER than the spike reference — the
    device's ceiling is a look decision, not a fitting one."""
    for text, register, _ in FITTED:
        band = stamp_band(W, H, text=text, text_register=register)
        assert band is not None
        assert band.font_size <= _STAMP_REF_FONT


def test_band_height_tracks_the_fitted_font():
    """Decision recorded in `stamp_band`: the band tracks the fitted
    size rather than staying the nominal 190-strip, so K4 keeps
    measuring a box that sits INSIDE the drawn ink instead of one that
    grows with every character the writer adds."""
    for text, register, expected in FITTED:
        band = stamp_band(W, H, text=text, text_register=register)
        assert band is not None
        assert band.height == expected + 2 * band.pad
        assert band.height < 218
        # Top and width do NOT move: the strip stays full-bleed and
        # anchored, which is what K4's threshold tests measure.
        assert (band.left, band.top, band.width) == (0, 320, 720)


def test_empty_and_whitespace_text_resolve_the_reference_band():
    """Geometry-only callers (tests, degenerate-canvas checks) and a
    cue whose text somehow arrived blank must not collapse the band."""
    plain = stamp_band(W, H)
    assert plain is not None
    for text in ("", "   ", "\n\t"):
        band = stamp_band(W, H, text=text, text_register="en")
        assert band is not None
        assert band.as_props() == plain.as_props()


def test_degenerate_canvas_still_returns_none():
    assert stamp_band(0, 0, text="Tata Nexon", text_register="en") is None
    assert stamp_band(-10, 1280, text="Tata Nexon", text_register="en") is None


def test_punch_floor_is_below_the_phrases_that_were_approved():
    """The floor is what the prompt's character budget is derived from.
    If it ever rises above the fitted size of a phrase inside the
    budget, the budget in `prompts/emphasis/v1.md` is wrong too."""
    assert _STAMP_MIN_PUNCH_FONT == 90
    for text, register in (("Tata Nexon", "en"), ("बिकने वाली SUV", "hi")):
        band = stamp_band(W, H, text=text, text_register=register)
        assert band is not None
        assert band.font_size >= _STAMP_MIN_PUNCH_FONT


def test_usable_width_matches_the_slab_the_tsx_draws():
    assert _usable() == USABLE
    assert _STAMP_SLAB_INSETS == 4  # `padding: pad px (pad*2) px`, both sides


# ------------------------------------------------------------- the wiring


def _timeline_with_stamp(
    text: str,
    register: EmphasisRegister,
    *,
    render_style: str | None = None,
) -> Timeline:
    shot = Shot(
        id="sh_01",
        order=0,
        intent=ShotIntent.EXPLAIN,
        duration_s=3.0,
        emphasis_cue=EmphasisCue(
            device=EmphasisDevice.STAMP,
            anchor_fragment=1,
            text=text,
            text_register=register,
            offset_s=0.0,
        ),
    )
    scene = Scene(id="sc_01", order=0, title="t", duration_s=3.0, shots=[shot])
    return Timeline(
        timeline_id="t1",
        project_id="p1",
        version=1,
        produced_by=ProducedBy.NARRATION,
        status=TimelineStatus.DRAFT,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        metadata=TimelineMetadata(render_style=render_style),
        scenes=[scene],
    )


STAMP_TSX = Path(__file__).resolve().parents[4] / "compositor" / "src" / "Stamp.tsx"
COUNTER_TSX = Path(__file__).resolve().parents[4] / "compositor" / "src" / "Counter.tsx"


def test_the_tsx_still_forbids_a_wrap_and_still_insets_the_slab_by_4_pad():
    """The two facts about `Stamp.tsx` this module's arithmetic assumes,
    pinned across the language boundary the way `test_stamp_word_timing`
    pins the schedule. `whiteSpace: nowrap` is the guarantee that a bad
    measurement cannot break a word, and `padding: pad px (pad*2) px` is
    what `_STAMP_SLAB_INSETS = 4` mirrors — delete either and the fit
    goes back to being a hope. Review finding 3's lesson: two copies of
    one number, only one of which draws anything."""
    source = STAMP_TSX.read_text(encoding="utf-8")
    assert 'whiteSpace: "nowrap"' in source
    assert "padding: onSlab ? `${pad}px ${pad * 2}px` : 0," in source


def test_bare_stamp_and_counter_use_caption_outline_not_shadow_or_halo():
    """K16.7: bare paths take CaptionStyle.outline_fraction (0.006 → 8px
    on 720×1280) via WebkitTextStroke + paintOrder; slab does not.
    SHADOW/HALO are gone as the bare-type protection."""
    stamp = STAMP_TSX.read_text(encoding="utf-8")
    counter = COUNTER_TSX.read_text(encoding="utf-8")
    for source in (stamp, counter):
        assert "OUTLINE_FRACTION = 0.006" in source
        assert "WebkitTextStroke" in source
        assert 'paintOrder: "stroke fill"' in source
        assert "CaptionStyle.outline_fraction" in source
        assert "const SHADOW" not in source
        assert "const HALO" not in source
    # Slab skips the outline object.
    assert "bareOutline = onSlab" in stamp
    assert "bareOutline = onSlab" in counter
    # Mirror the TSX: Math.max(1, Math.round(Math.max(w,h) * 0.006)).
    assert max(1, round(max(720, 1280) * 0.006)) == 8


def test_collect_passes_the_phrase_and_its_register_into_the_band():
    """The band is only content-derived if the content reaches it. The
    register has to travel too: the same 14 characters are 93px in
    Devanagari and would be far smaller in the heavy Latin stack."""
    hi = collect_emphasis_overlay_cues(
        _timeline_with_stamp("बिकने वाली SUV", EmphasisRegister.HI),
        fps=30,
        width=W,
        height=H,
    )
    assert hi[0].band is not None
    assert hi[0].band.font_size == 93

    en = collect_emphasis_overlay_cues(
        _timeline_with_stamp("Tata Nexon", EmphasisRegister.EN),
        fps=30,
        width=W,
        height=H,
    )
    assert en[0].band is not None
    assert en[0].band.font_size == 94

    same_text_wrong_register = stamp_text_width(
        text="बिकने वाली SUV", text_register="en", font_size=100
    )
    assert same_text_wrong_register != stamp_text_width(
        text="बिकने वाली SUV", text_register="hi", font_size=100
    )


def test_a_longer_phrase_misses_the_overlay_cache_of_a_shorter_one():
    """Two phrases that resolve different fonts must not share a `.mov`.
    The band is in both hash payloads, so this falls out of the change
    — pinned because it is the property that stops a cached overlay
    being served with the type at the old size."""
    short = collect_emphasis_overlay_cues(
        _timeline_with_stamp("Nexon", EmphasisRegister.EN), fps=30, width=W, height=H
    )
    long = collect_emphasis_overlay_cues(
        _timeline_with_stamp("Tata Nexon", EmphasisRegister.EN),
        fps=30,
        width=W,
        height=H,
    )
    assert short[0].band.font_size != long[0].band.font_size
    assert emphasis_cue_content_hash(short) != emphasis_cue_content_hash(long)


def test_stamp_band_default_top_stays_320_on_720x1280():
    """K16.4 / K15 control: no top_fraction → today's 320 (25% down)."""
    band = stamp_band(W, H)
    assert band is not None
    assert band.top == 320
    assert band.top / H == 0.25


def test_stamp_band_top_fraction_018_is_230_on_720x1280():
    """K16.4: retention_fast's 0.18 → top 230 on 1280 (18% down)."""
    band = stamp_band(W, H, top_fraction=0.18)
    assert band is not None
    assert band.top == round(0.18 * H) == 230


def test_collect_stamp_top_fraction_018_is_230():
    """K16.4 finding 3: collect no longer reads render_style; the caller
    passes the resolved fraction. 0.18 → top 230 on 1280."""
    cues = collect_emphasis_overlay_cues(
        _timeline_with_stamp("Parts", EmphasisRegister.EN),
        fps=30,
        width=W,
        height=H,
        stamp_top_fraction=0.18,
    )
    assert len(cues) == 1
    assert cues[0].band is not None
    assert cues[0].band.top == 230


def test_collect_without_stamp_top_fraction_keeps_320():
    """None / omitted fraction → today's `_STAMP_REF_TOP` scale (320)."""
    cues = collect_emphasis_overlay_cues(
        _timeline_with_stamp("Parts", EmphasisRegister.EN),
        fps=30,
        width=W,
        height=H,
    )
    assert cues[0].band is not None
    assert cues[0].band.top == 320

    cues_none = collect_emphasis_overlay_cues(
        _timeline_with_stamp("Parts", EmphasisRegister.EN),
        fps=30,
        width=W,
        height=H,
        stamp_top_fraction=None,
    )
    assert cues_none[0].band is not None
    assert cues_none[0].band.top == 320
