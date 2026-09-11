"""K18 - character-budget chunking of long Feature A karaoke lines
inside `serialize_ass` (retention_fast_kinetic_text.md).

One CaptionCue stays one sentence (K17 placement untouched). Chunking
only changes which words appear on each Dialogue line. Words-per-block
is readable by stripping ASS override tags from each Dialogue text.
"""

from __future__ import annotations

import re

from app.renderer.caption_placement import CaptionPlacement
from app.renderer.captions import (
    CaptionCue,
    CaptionStyle,
    CaptionWord,
    format_ass_time,
    serialize_ass,
)

_STYLE = CaptionStyle(resolution=(1080, 1920), font_family="Noto Sans Devanagari")
_CHUNKED = CaptionStyle(
    resolution=(1080, 1920),
    font_family="Noto Sans Devanagari",
    chunk_chars=28,
)
_TAG_PATTERN = re.compile(r"\{\\[^}]*\}")


def _cue(
    text: str, start: float, end: float, *word_windows: tuple[str, float, float]
) -> CaptionCue:
    return CaptionCue(
        start_s=start,
        end_s=end,
        text=text,
        words=tuple(CaptionWord(text=t, start_s=s, end_s=e) for t, s, e in word_windows),
    )


def _dialogue_lines(ass: str) -> list[str]:
    return [line for line in ass.splitlines() if line.startswith("Dialogue:")]


def _visible_text(line: str) -> str:
    """Tags stripped; Dialogue text after MarginL/R/V and empty Effect."""
    # Dialogue: 0,start,end,Caption,,ML,MR,MV,,TEXT
    after_caption = line.split("Caption,,", 1)[1]
    _margins, text = after_caption.split(",,", 1)
    return _TAG_PATTERN.sub("", text)


def _window(line: str) -> tuple[str, str]:
    fields = line.split(",")
    return fields[1], fields[2]


def _margins_and_an(line: str) -> tuple[str, str, str, str | None]:
    after_caption = line.split("Caption,,", 1)[1]
    margins, text = after_caption.split(",,", 1)
    ml, mr, mv = margins.split(",")
    an_match = re.match(r"\{\\an(\d+)\}", text)
    an = an_match.group(1) if an_match else None
    return ml, mr, mv, an


def _nine_word_hinglish() -> CaptionCue:
    # "Bharat mein aap jo bhi videshi samaan kharidte hain."
    # Budget 28 greedy: "Bharat mein aap jo bhi" (22) then
    # "videshi samaan kharidte" (23) then "hain." (5).
    words = (
        ("Bharat", 0.0, 0.3),
        ("mein", 0.3, 0.5),
        ("aap", 0.5, 0.7),
        ("jo", 0.7, 0.9),
        ("bhi", 0.9, 1.1),
        ("videshi", 1.1, 1.4),
        ("samaan", 1.4, 1.7),
        ("kharidte", 1.7, 2.1),
        ("hain.", 2.1, 2.4),
    )
    return _cue(
        "Bharat mein aap jo bhi videshi samaan kharidte hain.",
        0.0,
        2.4,
        *words,
    )


def test_chunk_chars_28_keeps_joined_block_len_at_most_28():
    dialogue = _dialogue_lines(serialize_ass([_nine_word_hinglish()], _CHUNKED))
    blocks = {_visible_text(line) for line in dialogue}
    for block in blocks:
        assert len(block) <= 28, block


def test_nine_word_sentence_splits_into_short_blocks_not_whole_sentence():
    dialogue = _dialogue_lines(serialize_ass([_nine_word_hinglish()], _CHUNKED))
    seen: list[str] = []
    for line in dialogue:
        text = _visible_text(line)
        if not seen or seen[-1] != text:
            seen.append(text)
    word_counts = [len(b.split()) for b in seen]
    assert all(c <= 5 for c in word_counts)
    assert max(word_counts) >= 4  # typical Hinglish 4–5 on the long chunks
    assert "Bharat mein aap jo bhi videshi samaan kharidte hain." not in seen
    assert seen == [
        "Bharat mein aap jo bhi",
        "videshi samaan kharidte",
        "hain.",
    ]


def test_chunk_windows_tile_cue_with_zero_gaps_and_no_overlap():
    cue = _nine_word_hinglish()
    dialogue = _dialogue_lines(serialize_ass([cue], _CHUNKED))
    windows = [_window(line) for line in dialogue]
    assert windows[0][0] == format_ass_time(cue.start_s)
    for i in range(len(windows) - 1):
        assert windows[i][1] == windows[i + 1][0], (windows[i], windows[i + 1])
    assert windows[-1][1] == format_ass_time(cue.end_s)


def test_highlight_walks_inside_chunk_only():
    dialogue = _dialogue_lines(serialize_ass([_nine_word_hinglish()], _CHUNKED))
    first_block = "Bharat mein aap jo bhi"
    first_block_lines = [
        line for line in dialogue if _visible_text(line) == first_block
    ]
    assert len(first_block_lines) == 5
    assert "{\\c&H00FFFF&}Bharat{\\r} mein aap jo bhi" in first_block_lines[0]
    assert "Bharat {\\c&H00FFFF&}mein{\\r} aap jo bhi" in first_block_lines[1]
    assert "Bharat mein {\\c&H00FFFF&}aap{\\r} jo bhi" in first_block_lines[2]
    assert "Bharat mein aap {\\c&H00FFFF&}jo{\\r} bhi" in first_block_lines[3]
    assert "Bharat mein aap jo {\\c&H00FFFF&}bhi{\\r}" in first_block_lines[4]
    for line in first_block_lines:
        assert line.count("{\\c&H00FFFF&}") == 1
        assert "videshi" not in line


def test_all_chunks_of_one_cue_share_k17_placement():
    cue = _nine_word_hinglish()
    placement = CaptionPlacement(
        name="bottom_left",
        an=1,
        margin_l=60,
        margin_r=20,
        margin_v=205,
        box=(0, 900, 700, 1100),
    )
    dialogue = _dialogue_lines(
        serialize_ass([cue], _CHUNKED, placements=[placement])
    )
    assert len(dialogue) > 4  # more than one chunk's worth
    for line in dialogue:
        ml, mr, mv, an = _margins_and_an(line)
        assert (ml, mr, mv, an) == ("60", "20", "205", "1")


def test_word_less_cue_byte_identical_with_chunk_chars_set():
    cue = CaptionCue(start_s=7.059, end_s=10.5, text="hello world")
    assert serialize_ass([cue], _CHUNKED) == serialize_ass([cue], _STYLE)


def test_short_phrase_under_budget_keeps_whole_sentence_feature_a():
    """Existing highlight pin: 'no one will say' is 15 chars < 28."""
    cue = _cue(
        "no one will say",
        1.0,
        2.0,
        ("no", 1.0, 1.2),
        ("one", 1.2, 1.5),
        ("will", 1.5, 1.7),
        ("say", 1.7, 2.0),
    )
    dialogue = _dialogue_lines(serialize_ass([cue], _CHUNKED))
    assert len(dialogue) == 4
    assert all(_visible_text(line) == "no one will say" for line in dialogue)
    assert "{\\c&H00FFFF&}no{\\r} one will say" in dialogue[0]
    assert "no one will {\\c&H00FFFF&}say{\\r}" in dialogue[3]


def test_comma_preference_flushes_after_rightmost_clause_mark():
    """Greedy would pack past 'then,'; comma preference flushes there."""
    # "Well then, we can see this clearly"
    # Well then, we can see this = 25; + clearly = 33 > 28.
    # Greedy pack: Well then, we can see this.
    # 'then,' is a non-first clause mark leaving packed words after it
    # → flush after 'then,' → "Well then," then "we can see this clearly".
    cue = _cue(
        "Well then, we can see this clearly",
        0.0,
        3.4,
        ("Well", 0.0, 0.3),
        ("then,", 0.3, 0.6),
        ("we", 0.6, 0.9),
        ("can", 0.9, 1.2),
        ("see", 1.2, 1.5),
        ("this", 1.5, 1.8),
        ("clearly", 1.8, 2.4),
    )
    dialogue = _dialogue_lines(serialize_ass([cue], _CHUNKED))
    seen: list[str] = []
    for line in dialogue:
        text = _visible_text(line)
        if not seen or seen[-1] != text:
            seen.append(text)
    assert seen == ["Well then,", "we can see this clearly"]


def test_oversize_single_word_is_its_own_block():
    long_word = "x" * 40
    cue = _cue(
        f"hi {long_word} bye",
        0.0,
        3.0,
        ("hi", 0.0, 0.5),
        (long_word, 0.5, 2.0),
        ("bye", 2.0, 3.0),
    )
    dialogue = _dialogue_lines(serialize_ass([cue], _CHUNKED))
    seen: list[str] = []
    for line in dialogue:
        text = _visible_text(line)
        if not seen or seen[-1] != text:
            seen.append(text)
    assert seen == ["hi", long_word, "bye"]
    assert len(long_word) > 28


def test_serialize_ass_and_chunker_do_not_reference_caption_word_groups():
    import inspect

    from app.renderer import captions as captions_mod

    source = inspect.getsource(captions_mod.serialize_ass)
    chunk_source = inspect.getsource(captions_mod._chunk_word_ranges)
    highlighted = inspect.getsource(captions_mod._highlighted_dialogue_lines)
    for blob in (source, chunk_source, highlighted):
        assert "caption_word_groups" not in blob
