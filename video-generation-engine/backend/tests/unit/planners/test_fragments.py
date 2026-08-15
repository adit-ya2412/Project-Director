"""`app/planners/shot/fragments.py` (M5 hardening, 2026-08-15) - pure,
fast, no network, no model. The actual fix for three incidents of the
Shot Planner doing unreliable character arithmetic: a mid-word split
("Leuna-Werke" -> "L" + "euna-Werke") and a mid-grapheme-cluster split
("दिन" -> "द" + "िन") both become structurally impossible once shots are
assigned whole fragments rather than raw character offsets - these
tests prove that directly against the exact measured bug text, not
merely against the algorithm's own internal logic.
"""

from app.planners.shot.fragments import split_narration_fragments


def _reconstruct(text: str) -> str:
    return "".join(text[f.start : f.end] for f in split_narration_fragments(text))


def test_lossless_reconstruction_holds_for_every_case_in_this_file():
    """One property, checked once, that every other test in this file
    also implicitly depends on: no matter how the text is fragmented,
    concatenating every fragment's own span must reproduce the original
    text exactly - the property the Scene Planner's own verbatim check
    ultimately rests on."""
    cases = [
        "Germany की war machine\nइससे बने fuel पर चल रही थी।\n\n"
        "Leuna-Werke जैसी factories\nदिन-रात fuel बना रही थीं।",
        "Leuna-Werke jaisi factories din raat fuel bana rahi thi.",
        "Bro this is one line only",
        "",
        "   leading and trailing whitespace   ",
    ]
    for text in cases:
        assert _reconstruct(text) == text


def test_a_latin_hyphenated_name_is_never_split():
    """The real bug: 'Leuna-Werke' was split into 'L' + 'euna-Werke' at
    its internal hyphen. The hyphen is deliberately not a split
    character (module docstring) - a compound/hyphenated name stays
    whole, whether it is the entire text or embedded in a longer line."""
    text = "Leuna-Werke jaisi factories din raat fuel bana rahi thi."
    fragments = split_narration_fragments(text)
    assert not any(f.text.startswith("euna-Werke") for f in fragments)
    assert not any(f.text.endswith("L") for f in fragments)
    # With no sentence-ending punctuation until the very end and well
    # under the long-fragment threshold, this stays one whole fragment.
    assert len(fragments) == 1
    assert fragments[0].text == text


def test_a_devanagari_grapheme_cluster_is_never_split():
    """The real bug's worst case: 'दिन' was split into 'द' + 'िन',
    separating a dependent vowel sign from its base consonant - not
    merely truncated text, malformed text. A newline right before
    'दिन-रात' is a legitimate fragment boundary; splitting a hyphenated
    Devanagari compound at the hyphen, or worse, inside the grapheme
    cluster itself, is not."""
    text = "Leuna-Werke jaisi factories\nदिन-rat fuel bana rahi thi."
    fragments = split_narration_fragments(text)
    reconstructed_pieces = [f.text for f in fragments]
    # The newline is a legitimate split - two fragments, not one.
    assert len(fragments) == 2
    # Neither fragment starts or ends mid-grapheme: "िन" (the dependent
    # vowel sign + what follows) never appears detached from "द".
    assert not any(piece.startswith("िन") for piece in reconstructed_pieces)
    assert not any(piece.endswith("द") for piece in reconstructed_pieces)
    assert reconstructed_pieces[1].startswith("दिन-rat")


def test_the_exact_reported_bug_scene_produces_no_mid_word_or_mid_cluster_fragment():
    """The full scene from the live bug report (project
    `2fa282b4-...`), reconstructed from the raw span dump in the
    coordinator's own message - all four measured defects
    ('Germany...इ' + 'ससे', 'थी।\\n\\nL' + 'euna-Werke', 'factories\\nद'
    + 'िन-रात', all in one scene) must be structurally absent."""
    text = (
        "Germany की war machine\nइससे बने fuel पर चल रही थी।\n\n"
        "Leuna-Werke जैसी factories\nदिन-रात fuel बना रही थीं।"
    )
    fragments = split_narration_fragments(text)
    pieces = [f.text for f in fragments]
    assert pieces == [
        "Germany की war machine",
        "इससे बने fuel पर चल रही थी।",
        "Leuna-Werke जैसी factories",
        "दिन-रात fuel बना रही थीं।",
    ]


def test_a_long_run_on_sentence_is_subdivided_on_clause_punctuation():
    """The opposite risk from splitting too eagerly: one sentence with
    no full stop until the very end must still be divisible across more
    than one shot once it is long enough - secondary clause splitting
    (commas, semicolons, colons, the em dash) exists for exactly this,
    applied only once a fragment exceeds the long-fragment threshold."""
    text = (
        "Germany had abundant coal, which powered its factories, fueled its trains, "
        "and sustained its industry for decades, but it lacked one vital resource: oil."
    )
    assert len(text) > 80  # must actually exceed the threshold to prove the point
    fragments = split_narration_fragments(text)
    assert len(fragments) > 1
    assert _reconstruct(text) == text
    # Every fragment boundary is still a real clause break, never mid-word.
    for f in fragments[:-1]:
        assert f.text[-1] in ",;:—"


def test_a_short_sentence_with_no_internal_punctuation_stays_one_fragment():
    """The other edge, symmetric to the long-sentence case: an ordinary
    short line under the threshold is left whole - this is the "one
    fragment, several shots" scenario the Shot Planner's own validator
    (not this module) decides what to do with."""
    text = "Bro this is one line only"
    fragments = split_narration_fragments(text)
    assert len(fragments) == 1
    assert fragments[0].text == text


def test_ellipsis_and_em_dash_followed_by_newline_are_left_alone():
    """Explicitly not 'fixed': a scene author's own stylistic pause
    ('…' or '—' followed by a line break) is already a legitimate
    fragment boundary, not a defect."""
    text = "The war dragged on…\nAnd then, the turn no one expected—\nfuel from coal."
    fragments = split_narration_fragments(text)
    assert [f.text for f in fragments] == [
        "The war dragged on…",
        "And then, the turn no one expected—",
        "fuel from coal.",
    ]
