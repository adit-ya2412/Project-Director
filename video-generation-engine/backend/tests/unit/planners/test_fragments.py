"""`app/planners/fragments.py` (M5 hardening, 2026-08-15; moved out of
`app/planners/shot/` in S2, 2026-08-16, once the Scene Planner started
sharing it) - pure, fast, no network, no model. The actual fix for three
incidents of the Shot Planner doing unreliable character arithmetic: a
mid-word split ("Leuna-Werke" -> "L" + "euna-Werke") and a
mid-grapheme-cluster split ("दिन" -> "द" + "िन") both become
structurally impossible once shots are assigned whole fragments rather
than raw character offsets - these tests prove that directly against
the exact measured bug text, not merely against the algorithm's own
internal logic.
"""

from app.planners.fragments import split_narration_fragments


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


# --- Whitespace-only fragments (2026-08-16) ---
#
# A second-order defect the fragment redesign itself surfaced on a real
# run: the user's script has blank lines between stanzas, and the Scene
# Planner's own verbatim check means that whitespace has to live
# somewhere - it lands at the front of the next scene's narration_text.
# Before this fix, that leading blank run became its OWN fragment, and
# the Shot Planner - correctly following its instructions to assign
# every fragment - gave it a shot: a real image, a Ken Burns move, and a
# slice of the video's duration, for a beat of silence. Two of the real
# project's 24 shots were exactly this (3 of 48 seconds).


def test_reported_scene_sc_03_no_longer_produces_a_blank_shot():
    """The exact scene from the live bug report. Before this fix:
    3 fragments, the first ('\\n\\n') entirely blank. After: the leading
    blank run is folded forward into the first REAL fragment, and no
    fragment is ever whitespace-only."""
    text = "\n\nइसका नाम था Fischer-Tropsch process.\n\n1925 में invent हुआ,"
    fragments = split_narration_fragments(text)
    assert _reconstruct(text) == text
    assert all(f.text != "" for f in fragments)  # no fragment is blank after .strip()
    assert len(fragments) == 2
    assert fragments[0].index == 1
    assert fragments[1].index == 2
    # The blank run is still THERE (lossless), just no longer its own
    # fragment - it is a leading part of fragment 1's own span.
    assert text[fragments[0].start : fragments[0].end].startswith("\n\n")
    assert fragments[0].text == "इसका नाम था Fischer-Tropsch process."
    assert fragments[1].text == "1925 में invent हुआ,"


def test_reported_scene_sc_05_no_longer_produces_a_blank_shot():
    """The second exact scene from the live bug report. Before this fix:
    2 fragments, the first ('\\n\\n') entirely blank - which, being a
    2-fragment scene, would have let the model give it its own shot
    exactly as it did for real. After: the leading blank run merges
    forward into the scene's one real sentence, leaving a single
    fragment (correctly - a one-sentence scene has one natural unit of
    content, whitespace notwithstanding)."""
    text = "\n\nअब यहाँ twist है।"
    fragments = split_narration_fragments(text)
    assert _reconstruct(text) == text
    assert all(f.text != "" for f in fragments)
    assert len(fragments) == 1
    assert fragments[0].index == 1
    assert text[fragments[0].start : fragments[0].end].startswith("\n\n")
    assert fragments[0].text == "अब यहाँ twist है।"


def test_a_blank_run_between_sentences_is_absorbed_by_the_preceding_fragment():
    """This test used to claim (and assert) that a blank run BETWEEN two
    sentences merges FORWARD into the fragment that follows it, by
    analogy with the leading-blank-run cases below. That assertion was
    never actually true of this input, and nothing had exercised it
    (found by re-running the real splitter directly, not by reasoning
    about the code in the abstract - the same way the fragment redesign
    itself was verified).

    The real behaviour: `_find_split_points` skips a trigger's trailing
    whitespace when computing where the NEXT fragment starts, so that
    whitespace already belongs to the END of the fragment BEFORE the
    trigger - there is no separate whitespace-only fragment left for the
    merge pass to fold forward. More generally, an INTERIOR (non-
    leading) whitespace-only fragment cannot arise via the primary or
    secondary split passes at all: every split point other than the
    mandatory 0 is, by construction, the position of a non-whitespace
    character, so a fragment starting there is never entirely blank.
    Confirmed by fuzzing the real splitter across ~200k random
    combinations of sentence/clause/newline tokens (2026-08-16): not one
    produced an interior whitespace-only fragment. See
    `app/planners/fragments.py`'s own docstring for the same argument.

    The forward-merge rule this test used to (wrongly) assert on is real
    but only ever fires for a LEADING blank run - see
    `test_reported_scene_sc_03_no_longer_produces_a_blank_shot` and its
    neighbour below, which exercise it on inputs that actually reach it."""
    text = "First sentence.\n\n\n\nSecond sentence."
    fragments = split_narration_fragments(text)
    assert _reconstruct(text) == text
    assert all(f.text != "" for f in fragments)
    assert len(fragments) == 2
    assert fragments[0].text == "First sentence."
    assert fragments[1].text == "Second sentence."
    # The blank run is TRAILING content of fragment 1 (the fragment
    # BEFORE it), not leading content of fragment 2 - the opposite of
    # what this test used to assert.
    assert text[fragments[0].start : fragments[0].end].endswith("\n\n\n\n")
    assert not text[fragments[1].start : fragments[1].end].startswith("\n")


def test_a_trailing_whitespace_only_fragment_would_merge_backward():
    """The "backward if it is last" half of the rule. In practice the
    splitter never manufactures a TRAILING standalone whitespace
    fragment on its own (trailing whitespace after the final split point
    is simply absorbed into the previous fragment's own span, never
    promoted to a new one) - this test pins that actual, simpler
    behaviour down directly, since it is what makes the backward branch
    unreachable via the splitter's own primary/secondary passes rather
    than an assumption."""
    text = "Real content here.\n\n   \n"
    fragments = split_narration_fragments(text)
    assert _reconstruct(text) == text
    assert len(fragments) == 1
    assert fragments[0].text == "Real content here."
    assert fragments[0].end == len(text)  # trailing whitespace absorbed, not split off


def test_degenerate_case_entirely_whitespace_narration_stays_one_blank_fragment():
    """The explicit decision for a scene with NO real narration content
    at all: left as a single whitespace-only fragment, since there is
    nothing else to merge it into. Not silently patched with invented
    content, and not a crash - an accepted, out-of-scope input (a scene
    with zero real narration is a planning-level defect elsewhere, not
    something this module can fix by producing words from nothing)."""
    text = "\n\n   \n"
    fragments = split_narration_fragments(text)
    assert _reconstruct(text) == text
    assert len(fragments) == 1
    assert fragments[0].text == ""
    assert fragments[0].start == 0
    assert fragments[0].end == len(text)


def test_degenerate_case_empty_narration_stays_one_blank_fragment():
    fragments = split_narration_fragments("")
    assert len(fragments) == 1
    assert fragments[0].text == ""
    assert fragments[0].start == fragments[0].end == 0
