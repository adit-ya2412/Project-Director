"""Burned captions (D2, docs/14_Captions_Plan.md): script text + TTS
alignment -> ASS cue file -> burned into the final video. Never
transcription of our own narration audio.

Two pure responsibilities, deliberately free of I/O and config reads so
they're testable without rendering anything (doc §4.1):

- `derive_caption_cues`: `(Timeline, per-scene narration rows) ->
  list[CaptionCue]`, in FINAL AUDIO-TRACK time (see "Which clock" below).
- `serialize_ass`: `list[CaptionCue] -> str`, deterministic ASS text.

`subtitles_filter_fragment` builds this module's piece of the shared
video filter pass (`app/renderer/video_filters.py`) as a `filter_complex`
string fragment - it does no I/O itself. Originally this module ran its
own standalone ffmpeg pass (`burn_captions`); that was generalised away
when docs/plans/watermark_implementation_plan.md needed the SAME
re-encode to also carry a watermark overlay, and two full re-encodes
after composition was the one thing worth avoiding (§1 there).

## Which clock: audio-concat time, not `compute_shot_start_times`

`app/renderer/audio.py::mux_narration` concatenates per-scene narration
audio back-to-back from t=0 (ffmpeg concat FILTER, decoded samples, no
gaps) - it has no knowledge of transitions at all. `app/timeline/
duration.py::compute_shot_start_times` computes a DIFFERENT timeline
(video-frame time, transition-overlap-aware). These agree at every scene
boundary except where a transition crosses a scene boundary, where they
diverge by exactly that transition's duration (measured on the real
fixture: sc_04->sc_05, off by 0.5s - see docs/14_Captions_Plan.md §10.2).
Since narration is the master clock (D1) and it's what the viewer
actually hears, cue times here are built by summing each scene's own
narration duration in order - the exact timeline `mux_narration`
produces - never by reusing `compute_shot_start_times`, which would
silently desync captions from the spoken words whenever a cross-scene
transition exists.

## Voice selection (the §0 trap)

This module does not resolve which narration row belongs to which
voice - it trusts `narration_rows` to already be one row per scene, in
`timeline.scenes` order, matching the timeline's current voice. That
resolution already exists, correctly, in `app/workflow/steps/
render.py::_resolve_narration_rows` (the same content-hash lookup
`_resolve_narration_audio` has always used) - duplicating it here would
be exactly the "same arithmetic in two places" trap this codebase's own
duration.py docstring warns about, just for voice resolution instead of
transition arithmetic.
"""

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.logging import get_logger
from app.models.narration import NarrationModel
from app.planners.fragments import split_narration_fragments
from app.renderer.video_filters import escape_ffmpeg_filter_path
from app.schemas.timeline import Scene, Timeline

logger = get_logger(__name__)

MAX_CHARS_PER_CUE = 70
MIN_CUE_DURATION_S = 0.8
MAX_CUE_DURATION_S = 6.0

# Vendored fonts (doc §8.4: single family, no fallback stack - libass's
# own fallback resolution is platform-dependent, disqualified under I5).
# Resolved from this module's own location, not cwd - unlike
# `settings.storage_root`, a vendored asset must not depend on which
# directory the process happened to be launched from.
FONT_DIR = Path(__file__).resolve().parents[2] / "vendor" / "fonts"
_FONT_FILES_BY_FAMILY = {
    "Noto Sans Devanagari": FONT_DIR / "NotoSansDevanagari-Regular.ttf",
}


def resolve_caption_font(font_family: str) -> Path:
    """Maps a configured font family name to its vendored file. Raises
    rather than silently falling back to a host font (§8.4) - a fallback
    here would reintroduce exactly the host-fontconfig non-determinism
    vendoring exists to remove."""
    try:
        path = _FONT_FILES_BY_FAMILY[font_family]
    except KeyError:
        raise ValueError(
            f"no vendored font for family {font_family!r} - available: "
            f"{sorted(_FONT_FILES_BY_FAMILY)}"
        ) from None
    if not path.exists():
        raise ValueError(f"vendored font file missing on disk: {path}")
    return path


def caption_font_content_hash(font_family: str) -> str:
    """The fingerprint's font input (doc §6): the FILE's content hash, not
    its name/path, so swapping the vendored file changes the fingerprint
    even when the configured family name string doesn't change."""
    return hashlib.sha256(resolve_caption_font(font_family).read_bytes()).hexdigest()


@dataclass(frozen=True)
class CaptionWord:
    """One whitespace-delimited token of a cue's text, with its own
    absolute speak window taken from the same per-character alignment the
    cue itself was built from (Feature A, style_extensions.md §3.2/§3.3 -
    never a second timing source). Punctuation stays attached to its
    token, so `world,` highlights including the comma."""

    text: str
    start_s: float
    end_s: float


@dataclass(frozen=True)
class CaptionCue:
    start_s: float
    end_s: float
    text: str
    # Feature A (style_extensions.md §3): populated by
    # `derive_caption_cues` from the same alignment arrays as everything
    # else; empty on hand-built cues, which serialise exactly as they did
    # before this feature existed.
    words: tuple[CaptionWord, ...] = ()


@dataclass(frozen=True)
class CaptionStyle:
    """Doc §8.2: white text, heavy black outline, no background box,
    raised clear of the bottom ~12-15% platform-UI band (TikTok/Reels/
    Shorts all overlay controls there). Sizes are fractions of frame
    height, not absolute points, so drafts and finals agree (§8.2) - but
    drafts never burn captions at all (§4.3), so this only ever runs at
    one resolution per render in practice."""

    resolution: tuple[int, int]
    font_family: str
    font_size_fraction: float = 0.045
    outline_fraction: float = 0.006
    margin_v_fraction: float = 0.16
    # retention_fast_kinetic_text.md K16.2: Feature A size/weight on the
    # highlighted word. None / False keep the historical colour-only
    # override byte-identical. Resolved once in the render caller (RV2)
    # and passed in — captions.py never reads a style band.
    highlight_size_fraction: float | None = None
    highlight_bold: bool = False
    # K16.3: Feature A highlight colour from the resolved palette accent
    # (`#RRGGBB`). None keeps today's yellow (`{\c&H00FFFF&}`) so other
    # styles / default CaptionStyle stay byte-identical.
    highlight_colour: str | None = None


def derive_caption_cues(
    timeline: Timeline,
    narration_rows: list[NarrationModel],
    *,
    max_chars: int = MAX_CHARS_PER_CUE,
    min_duration_s: float = MIN_CUE_DURATION_S,
    max_duration_s: float = MAX_CUE_DURATION_S,
) -> list[CaptionCue]:
    """`narration_rows[i]` must be the resolved narration for
    `timeline.scenes[i]` (see module docstring - voice selection is the
    caller's responsibility). Cues never straddle a shot cut (§8.1): each
    shot's own `narration_span` is segmented independently, never merged
    across a shot boundary, only within one.

    Caption *timing* is always derived from `narration_text` and the
    alignment arrays (those offsets are the TTS coordinate system).
    Caption *display strings* come from `scene.caption_text` when the
    romanizer has stored a same-word-count Latin rendering
    (caption_romanization.md §3.4), optionally merged N narration words
    into one display token via `scene.caption_word_groups` (§10.3-10.4:
    Hindi number words collapsed into one digit token, e.g. `1931`). The
    bridge between the two strings is word index, not character offset —
    the two strings are not comparable by character position. If
    `caption_text` is None, its word structure does not match
    `narration_text`, or a merged group would straddle a cue boundary
    (§10.5), this falls back to today's behaviour (display
    `narration_text` verbatim) — for a straddling group, for the WHOLE
    scene, not just the affected cue (§10.5's rejected alternatives
    explain why a narrower fallback is worse)."""
    if len(narration_rows) != len(timeline.scenes):
        raise ValueError(
            f"expected one narration row per scene ({len(timeline.scenes)}), "
            f"got {len(narration_rows)}"
        )

    cues: list[CaptionCue] = []
    scene_offset_s = 0.0
    for scene, row in zip(timeline.scenes, narration_rows, strict=True):
        char_starts = row.alignment["character_start_times_seconds"]
        char_ends = row.alignment["character_end_times_seconds"]
        scene_duration_s = char_ends[-1] if char_ends else 0.0

        aligned = _aligned_display_tokens(scene)
        scene_token_ranges = _token_char_spans(scene.narration_text, 0, len(scene.narration_text))

        # Segmentation is computed once per shot, up front, so the
        # straddle check (§10.5) and the actual cue text below see
        # EXACTLY the same segment boundaries — never re-derived.
        shot_segments: list[list[tuple[int, int]]] = []
        for shot in scene.shots:
            if shot.narration_span is None:
                continue
            span_start, span_end = shot.narration_span
            if span_end <= span_start:
                continue
            shot_segments.append(
                _segment_span(
                    scene.narration_text,
                    span_start,
                    span_end,
                    max_chars=max_chars,
                    min_duration_s=min_duration_s,
                    max_duration_s=max_duration_s,
                    char_starts=char_starts,
                    char_ends=char_ends,
                )
            )

        if aligned is not None and scene.caption_word_groups is not None:
            all_segments = [seg for segs in shot_segments for seg in segs]
            if _group_straddles_cue(scene.caption_word_groups, scene_token_ranges, all_segments):
                logger.warning(
                    "caption_romanizer.group_straddles_cue",
                    extra={"project_id": timeline.project_id, "scene_id": scene.id},
                )
                aligned = None

        for segments in shot_segments:
            for seg_start, seg_end in segments:
                narr_words = _word_spans(
                    scene.narration_text,
                    seg_start,
                    seg_end,
                    char_starts=char_starts,
                    char_ends=char_ends,
                    scene_offset_s=scene_offset_s,
                )
                mapped = (
                    _map_display_words(
                        scene.narration_text,
                        seg_start,
                        seg_end,
                        scene_token_ranges=scene_token_ranges,
                        display_tokens=aligned[0],
                        token_group_id=aligned[1],
                        narr_words=narr_words,
                    )
                    if aligned is not None
                    else None
                )
                if mapped is None:
                    text = scene.narration_text[seg_start:seg_end].strip()
                    words = narr_words
                else:
                    text, words = mapped
                if not text:
                    continue
                cues.append(
                    CaptionCue(
                        start_s=scene_offset_s + char_starts[seg_start],
                        end_s=scene_offset_s + char_ends[seg_end - 1],
                        text=text,
                        words=words,
                    )
                )
        scene_offset_s += scene_duration_s

    _assert_monotonic_non_overlapping(cues)
    return cues


def _segment_span(
    text: str,
    span_start: int,
    span_end: int,
    *,
    max_chars: int,
    min_duration_s: float,
    max_duration_s: float,
    char_starts: list[float],
    char_ends: list[float],
) -> list[tuple[int, int]]:
    """One shot's narration span -> readable cue spans (doc §3.3/§4.2).
    `split_narration_fragments` gives sentence/clause-level spans (built
    for planner prompts, not reading); this layers a character-budget
    merge pass on top, then a last-resort split for anything still too
    long or too slow to be one cue."""
    local_fragments = split_narration_fragments(text[span_start:span_end])
    pieces = [
        (span_start + f.start, span_start + f.end)
        for f in local_fragments
        if f.end > f.start and text[span_start + f.start : span_start + f.end].strip()
    ]
    if not pieces:
        return []

    merged = _merge_by_budget(
        pieces,
        max_chars=max_chars,
        min_duration_s=min_duration_s,
        char_starts=char_starts,
        char_ends=char_ends,
    )
    result: list[tuple[int, int]] = []
    for start, end in merged:
        result.extend(
            _split_if_too_long(
                text,
                start,
                end,
                max_chars=max_chars,
                max_duration_s=max_duration_s,
                char_starts=char_starts,
                char_ends=char_ends,
            )
        )
    return result


def _merge_by_budget(
    pieces: list[tuple[int, int]],
    *,
    max_chars: int,
    min_duration_s: float,
    char_starts: list[float],
    char_ends: list[float],
) -> list[tuple[int, int]]:
    """Greedy forward merge: fold a fragment into the one before it while
    the combined span still fits the character budget, OR the fragment
    accumulated so far would flash on screen for less than
    `min_duration_s`. Never merges backward across a shot boundary - the
    caller only ever passes fragments from one shot's own span."""
    merged: list[tuple[int, int]] = [pieces[0]]
    for start, end in pieces[1:]:
        cur_start, cur_end = merged[-1]
        cur_duration = char_ends[cur_end - 1] - char_starts[cur_start]
        merged_len = end - cur_start
        if merged_len <= max_chars or cur_duration < min_duration_s:
            merged[-1] = (cur_start, end)
        else:
            merged.append((start, end))
    return merged


def _split_if_too_long(
    text: str,
    start: int,
    end: int,
    *,
    max_chars: int,
    max_duration_s: float,
    char_starts: list[float],
    char_ends: list[float],
) -> list[tuple[int, int]]:
    """Last-resort split for a span still over budget after merging (rare
    with per-shot segmentation - shots average ~3s in the reference
    fixture - but not impossible). Splits at the whitespace run nearest
    the midpoint, deterministically; if there is none (a single very long
    word), returns the span unsplit rather than breaking a word."""
    duration = char_ends[end - 1] - char_starts[start]
    if end - start <= max_chars and duration <= max_duration_s:
        return [(start, end)]

    mid = (start + end) // 2
    split_at = None
    for offset in range(0, end - start):
        left, right = mid - offset, mid + offset
        if start < left < end and text[left - 1].isspace():
            split_at = left
            break
        if start < right < end and text[right - 1].isspace():
            split_at = right
            break
    if split_at is None:
        return [(start, end)]

    left_parts = _split_if_too_long(
        text,
        start,
        split_at,
        max_chars=max_chars,
        max_duration_s=max_duration_s,
        char_starts=char_starts,
        char_ends=char_ends,
    )
    right_parts = _split_if_too_long(
        text,
        split_at,
        end,
        max_chars=max_chars,
        max_duration_s=max_duration_s,
        char_starts=char_starts,
        char_ends=char_ends,
    )
    return left_parts + right_parts


def _token_char_spans(text: str, seg_start: int, seg_end: int) -> list[tuple[int, int]]:
    """Whitespace-delimited token ranges inside `[seg_start, seg_end)`,
    as `(first, last_inclusive)` character offsets into `text`. Same
    splitter Feature A uses (`text[index].isspace()`); punctuation
    attaches to its token. Extracted so the romanization word-index
    bridge (caption_romanization.md §3.4) and `_word_spans` cannot
    drift apart."""
    spans: list[tuple[int, int]] = []
    token_start: int | None = None
    for index in range(seg_start, seg_end):
        if text[index].isspace():
            if token_start is not None:
                spans.append((token_start, index - 1))
                token_start = None
        elif token_start is None:
            token_start = index
    if token_start is not None:
        spans.append((token_start, seg_end - 1))
    return spans


def _aligned_display_tokens(
    scene: Scene,
) -> tuple[tuple[str, ...], tuple[int, ...]] | None:
    """`caption_text` split into display tokens, paired with a
    `token_group_id` array mapping each scene-level NARRATION word index
    to the display-token index it belongs to. Returns None when the
    stored shape is missing or unusable, meaning "fall back to
    `narration_text`" for the caller.

    Two shapes, both re-validated here rather than trusted from storage
    (caption_romanization.md §10.3):

    - `scene.caption_word_groups is None` — today's plain 1:1 path.
      Word count must match `narration_text` exactly (the §2.2
      invariant); `token_group_id` is the identity mapping, so
      `_map_display_words` below merges nothing and produces
      byte-identical output to before groups existed.
    - `scene.caption_word_groups` present — §10.3's grouped shape:
      `len(caption_word_groups)` must equal the `caption_text` word
      count (one group per display token) and `sum(caption_word_groups)`
      must equal the `narration_text` word count (every narration word
      accounted for, in order). `token_group_id` is the flat expansion
      of the groups.

    Any mismatch in either shape means the stored text cannot be
    bridged by word index without desyncing Feature A highlight timing,
    so we fall back rather than guess. Character offsets between
    `caption_text` and `narration_text` are NOT comparable and are
    never mixed.

    BOTH sides are tokenised with `_token_char_spans`, deliberately —
    not `str.split()`. `_map_display_words` indexes into ranges that
    come from `_token_char_spans`, so a guard using any other splitter
    could authorise the bridge on a count the bridge itself does not
    agree with, and `_word_index_containing` would then return an
    in-range but WRONG index: §2.2's failure mode slipping past §2.2's
    own guard. No input is known where the two splitters disagree
    (NEL, NBSP, U+2028, ideographic space, file separator and
    repeated/leading/trailing whitespace were all probed) — this is
    hardening against future drift, not a fix for a live bug.
    """
    if scene.caption_text is None:
        return None
    display_spans = _token_char_spans(scene.caption_text, 0, len(scene.caption_text))
    narration_spans = _token_char_spans(scene.narration_text, 0, len(scene.narration_text))
    display_tokens = tuple(
        scene.caption_text[first : last_inclusive + 1] for first, last_inclusive in display_spans
    )

    groups = scene.caption_word_groups
    if groups is None:
        if len(display_spans) != len(narration_spans):
            return None
        return display_tokens, tuple(range(len(narration_spans)))

    if len(groups) != len(display_spans):
        return None
    if any(g < 1 for g in groups):
        return None
    if sum(groups) != len(narration_spans):
        return None
    token_group_id: list[int] = []
    for group_index, covers in enumerate(groups):
        token_group_id.extend([group_index] * covers)
    return display_tokens, tuple(token_group_id)


def _group_straddles_cue(
    groups: list[int],
    scene_token_ranges: list[tuple[int, int]],
    segments: list[tuple[int, int]],
) -> bool:
    """§10.5: True when a merged group's (`covers > 1`) narration tokens
    are not all contained inside a SINGLE cue segment — the one
    genuinely new edge case grouping introduces. An unmerged group
    (`covers == 1`) can never straddle: `_split_if_too_long` only ever
    cuts at a whitespace run, so a single narration token is never torn
    across two cues.

    `segments` is every `(seg_start, seg_end)` cue span for the whole
    scene (across every shot, in the order cues are emitted) — a group
    must fall entirely within ONE of them, not merely overlap several.
    Callers must only invoke this after `_aligned_display_tokens` has
    already confirmed `sum(groups) == len(scene_token_ranges)`, so
    indexing `scene_token_ranges` by cumulative `covers` is safe here.
    """
    token_index = 0
    for covers in groups:
        if covers > 1:
            first_start = scene_token_ranges[token_index][0]
            last_end = scene_token_ranges[token_index + covers - 1][1]
            if not any(
                seg_start <= first_start and last_end < seg_end for seg_start, seg_end in segments
            ):
                return True
        token_index += covers
    return False


def _word_index_containing(ranges: list[tuple[int, int]], char_index: int) -> int | None:
    for i, (start, end) in enumerate(ranges):
        if start <= char_index <= end:
            return i
    return None


def _map_display_words(
    narration_text: str,
    seg_start: int,
    seg_end: int,
    *,
    scene_token_ranges: list[tuple[int, int]],
    display_tokens: tuple[str, ...],
    token_group_id: tuple[int, ...],
    narr_words: tuple[CaptionWord, ...],
) -> tuple[str, tuple[CaptionWord, ...]] | None:
    """Bridge a character span in `narration_text` to the corresponding
    `caption_text` words **by word index**, merging consecutive
    narration tokens that share a `token_group_id` into ONE
    `CaptionWord` (§10.4).

    Segment boundaries are character offsets into `narration_text`
    (the alignment arrays index that string). Display words live in a
    different string. The only safe join is the scene-level word index
    of each narration token — which is well-defined only because the
    romanizer enforces equal word count and order (caption_romanization.md
    §2.2/§10.3). A merged `CaptionWord`'s `start_s` is its first source
    word's `start_s`; `end_s` is its last source word's `end_s` — no new
    timing source, only a coarser grouping of the existing ones. Returns
    None to mean "fall back to narration_text".
    """
    char_spans = _token_char_spans(narration_text, seg_start, seg_end)
    # Unreachable: `narr_words` comes from `_word_spans`, which builds
    # it from `_token_char_spans` with these exact arguments. Kept as a
    # defensive guard so the indexing below can never go out of range.
    if len(char_spans) != len(narr_words):
        return None
    group_ids: list[int] = []
    for first, _last in char_spans:
        idx = _word_index_containing(scene_token_ranges, first)
        if idx is None or idx >= len(token_group_id):
            return None
        gid = token_group_id[idx]
        if gid >= len(display_tokens):
            return None
        group_ids.append(gid)

    labels: list[str] = []
    words: list[CaptionWord] = []
    i = 0
    n = len(group_ids)
    while i < n:
        j = i
        while j + 1 < n and group_ids[j + 1] == group_ids[i]:
            j += 1
        label = display_tokens[group_ids[i]]
        labels.append(label)
        words.append(
            CaptionWord(text=label, start_s=narr_words[i].start_s, end_s=narr_words[j].end_s)
        )
        i = j + 1

    text = " ".join(labels)
    return text, tuple(words)


def _word_spans(
    text: str,
    seg_start: int,
    seg_end: int,
    *,
    char_starts: list[float],
    char_ends: list[float],
    scene_offset_s: float,
) -> tuple[CaptionWord, ...]:
    """Feature A: one cue's character span -> its whitespace-delimited
    words, each timed by the SAME per-character alignment arrays that
    timed the cue itself (`char_starts[first_char]` ..
    `char_ends[last_char]`, plus the scene's audio-track offset). No new
    timing source is consulted anywhere (§3.2's critical constraint).
    Punctuation attaches to its token; a token whose alignment window
    collapses to zero length is kept - the serialiser decides what to do
    with it, keeping this function purely mechanical."""
    return tuple(
        CaptionWord(
            text=text[first : last_inclusive + 1],
            start_s=scene_offset_s + char_starts[first],
            end_s=scene_offset_s + char_ends[last_inclusive],
        )
        for first, last_inclusive in _token_char_spans(text, seg_start, seg_end)
    )


def _assert_monotonic_non_overlapping(cues: list[CaptionCue]) -> None:
    """A violated invariant here means the offset arithmetic above is
    wrong - fail loudly rather than ship silent drift (doc §4.2 step 5)."""
    for previous, current in zip(cues, cues[1:], strict=False):
        if current.start_s < previous.start_s:
            raise ValueError(f"caption cues not monotonic: {previous!r} then {current!r}")
        if current.start_s < previous.end_s - 1e-6:
            raise ValueError(f"caption cues overlap: {previous!r} then {current!r}")


def cue_list_content_hash(cues: list[CaptionCue]) -> str:
    """The fingerprint's cue-list input (doc §6): covers script edits,
    re-narration with a different voice, any segmentation-rule change,
    and (style_extensions.md §9 RV-A1) whether cues carry word-level
    highlight timing - so shipping Feature A forces every existing
    project through exactly one fresh render (cache MISS) instead of a
    cache HIT silently serving its old non-highlighted bytes forever.
    Fixed precision, stable ordering - never locale-dependent float
    formatting.

    Word timings deliberately get NO separate `compute_render_fingerprint`
    parameter (§9 RV-A2): they are a pure, deterministic function of
    `(narration_text, span bounds, alignment arrays, scene offset)` - the
    very inputs that already determine `start_s`/`end_s`/`text`, captured
    here and by the narration content-hash. Folding them into this digest
    is therefore sufficient; there is no independent degree of freedom an
    editor of `_word_spans` could change without this hash moving.

    Romanized display text (caption_romanization.md §3.4) is the same
    argument: cue `text` and each `CaptionWord.text` are hashed here, so
    a scene whose `caption_text` is filled hashes differently from the
    mixed-script original and forces exactly one correct re-render. No
    new fingerprint parameter is needed — the same transitive claim as
    Feature A's `words` (style_extensions.md §9 RV-A2)."""
    digest_input = "|".join(
        f"{c.start_s:.3f},{c.end_s:.3f},{c.text}"
        # Word-less cues keep the legacy byte format exactly; word-carrying
        # cues hash differently than their pre-Feature-A equivalents.
        + "".join(f";{w.text}@{w.start_s:.3f}-{w.end_s:.3f}" for w in c.words)
        for c in cues
    ).encode()
    return hashlib.sha256(digest_input).hexdigest()


def format_ass_time(seconds: float) -> str:
    """Public since 2026-08-17 - `app/renderer/text_cards.py` needs the
    identical ASS `H:MM:SS.CC` formatting and there is no captions-
    specific logic here to duplicate, matching the S2 precedent (one
    deterministic algorithm, one place it can be wrong)."""
    total_centiseconds = round(seconds * 100)
    centiseconds = total_centiseconds % 100
    total_seconds = total_centiseconds // 100
    s = total_seconds % 60
    total_minutes = total_seconds // 60
    m = total_minutes % 60
    h = total_minutes // 60
    return f"{h:d}:{m:02d}:{s:02d}.{centiseconds:02d}"


def _escape_ass_text(text: str) -> str:
    """Braces are ASS override-tag delimiters and backslash starts an
    escape/tag sequence - both must be escaped in literal cue text, or a
    narration line containing either would corrupt the event line."""
    text = text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")
    return text.replace("\n", " ").replace("\r", " ")


# Feature A (style_extensions.md §3.3): word-level highlight colour, in
# ASS's &HBBGGRR& order - yellow is B=00 G=FF R=FF. Default when
# `CaptionStyle.highlight_colour` is unset (K16.3); retention_fast feeds
# the resolved palette accent instead.
_HIGHLIGHT_COLOUR_ASS = "\\c&H00FFFF&"
_RESET_OVERRIDE_ASS = "{\\r}"
_HEX_RRGGBB = re.compile(r"^#[0-9A-Fa-f]{6}$")


def highlight_colour_to_ass(hex_rrggbb: str | None) -> str:
    """`#RRGGBB` → ASS `\\c&HBBGGRR&`. Invalid / missing → yellow.

    `#00D9FF` (project cyan accent) → `\\c&HFFD900&`. Pin lives in
    `test_caption_highlight.py`.
    """
    if hex_rrggbb is None or not _HEX_RRGGBB.fullmatch(hex_rrggbb):
        return _HIGHLIGHT_COLOUR_ASS
    r = hex_rrggbb[1:3]
    g = hex_rrggbb[3:5]
    b = hex_rrggbb[5:7]
    return f"\\c&H{b.upper()}{g.upper()}{r.upper()}&"


def _highlight_override_ass(style: CaptionStyle, axis: int) -> str:
    """Per-word ASS override. Tag order is stable: \\fs, then \\b1, then
    colour. Defaults (no size, no bold, no colour) emit exactly
    `{\\c&H00FFFF&}` — byte-identical to pre-K16.2 Feature A."""
    parts: list[str] = []
    if style.highlight_size_fraction is not None:
        size = max(round(axis * style.highlight_size_fraction), 1)
        parts.append(f"\\fs{size}")
    if style.highlight_bold:
        parts.append("\\b1")
    parts.append(highlight_colour_to_ass(style.highlight_colour))
    return "{" + "".join(parts) + "}"


def _placement_margins_and_prefix(placement: Any | None) -> tuple[str, str, str, str]:
    """MarginL/R/V strings and an optional ``{\\anN}`` text prefix.

    ``placement is None`` keeps today's ``0,0,0`` and no ``\\an``
    (byte-identical). Duck-typed so this module never imports
    ``CaptionPlacement`` (that neighbour does I/O; importing it would
    also cycle through ``CaptionCue``).
    """
    if placement is None:
        return "0", "0", "0", ""
    return (
        str(placement.margin_l),
        str(placement.margin_r),
        str(placement.margin_v),
        f"{{\\an{placement.an}}}",
    )


def _plain_dialogue_line(cue: CaptionCue, *, placement: Any | None = None) -> str:
    """The pre-Feature-A event line: whole cue, no highlight overrides."""
    ml, mr, mv, an_prefix = _placement_margins_and_prefix(placement)
    return (
        f"Dialogue: 0,{format_ass_time(cue.start_s)},{format_ass_time(cue.end_s)},"
        f"Caption,,{ml},{mr},{mv},,{an_prefix}{_escape_ass_text(cue.text)}"
    )


def _highlighted_dialogue_lines(
    cue: CaptionCue, *, highlight_override: str, placement: Any | None = None
) -> list[str]:
    """Feature A (§3.3, Option 2 - N contiguous lines instead of karaoke
    tags):
    word i's event spans [w_i.start, w_{i+1}.start) (the last word runs to
    the cue's end) and re-emits the WHOLE phrase with only word i wrapped
    in the highlight override. The windows tile the cue exactly - full
    coverage, zero overlap, and no karaoke arithmetic for libass to
    mis-scale. A highlighted word stays lit through any inter-word pause
    until the next word begins, which is the intended Hormozi-style
    behaviour. A word whose alignment window collapses to zero duration
    gets NO line of its own (libass rejects zero-duration events); its
    instant is already covered by the neighbouring window. Cues without
    words serialise byte-for-byte as they did before Feature A.

    K17: every word-walk line of one cue shares the same margins / ``\\an``.
    ``{\\anN}`` prefixes the existing highlight tags when a placement is set.
    """
    ml, mr, mv, an_prefix = _placement_margins_and_prefix(placement)

    def _line(highlight_index: int, start_s: float, end_s: float) -> str:
        tokens = [_escape_ass_word(w.text) for w in cue.words]
        tokens[highlight_index] = (
            f"{highlight_override}{tokens[highlight_index]}{_RESET_OVERRIDE_ASS}"
        )
        return (
            f"Dialogue: 0,{format_ass_time(start_s)},{format_ass_time(end_s)},"
            f"Caption,,{ml},{mr},{mv},,{an_prefix}{' '.join(tokens)}"
        )

    lines: list[str] = []
    for index, word in enumerate(cue.words):
        start = cue.start_s if index == 0 else word.start_s
        end = cue.end_s if index == len(cue.words) - 1 else cue.words[index + 1].start_s
        if end <= start + 1e-9:
            continue
        lines.append(_line(index, start, end))
    # Degenerate alignment (every window zero-length) must not drop the
    # caption entirely - fall back to the plain whole-cue line.
    return lines if lines else [_plain_dialogue_line(cue, placement=placement)]


def _escape_ass_word(word: str) -> str:
    """Same brace/backslash escaping as `_escape_ass_text`, minus newline
    flattening - tokens from `_word_spans` can never contain whitespace by
    construction, so this is a single mechanical replacement pass (RV-A3:
    no defensive re-split). Kept separate from `_escape_ass_text` so a
    future change to one rule cannot silently alter the other."""
    return word.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")


def serialize_ass(
    cues: list[CaptionCue],
    style: CaptionStyle,
    placements: list[Any | None] | None = None,
) -> str:
    """Pure. Fixed decimal precision, stable ordering, no `datetime.now()`
    or other non-deterministic content anywhere (I5, doc §5).

    ``placements`` is K17: one resolved block placement per cue (or None
    slots). ``placements is None`` keeps every Dialogue line at
    ``0,0,0`` with no ``\\an`` — byte-identical to pre-K17. A placement
    emits ``MarginL/R/V`` on the event and prefixes ``{\\anN}`` on the
    text (including word-less cues and Feature A word-walk lines).
    """
    width, height = style.resolution
    # Long side so 720×1280 and 1280×720 get the same 58 px caption
    # (§19.3). Portrait keeps today's height-based size.
    axis = max(width, height)
    font_size = max(round(axis * style.font_size_fraction), 1)
    outline = max(round(axis * style.outline_fraction), 1)
    margin_v = max(round(height * style.margin_v_fraction), 0)
    if width > height:
        # No vertical-feed UI band on landscape (§19.3).
        margin_v = max(round(height * 0.04), 0)

    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {width}",
        f"PlayResY: {height}",
        "WrapStyle: 0",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        # White primary, black outline, fully transparent back (no box -
        # BorderStyle=1 means outline, not a filled box), bottom-center
        # alignment (2) raised by MarginV to clear the platform UI band.
        f"Style: Caption,{style.font_family},{font_size},&H00FFFFFF,&H00FFFFFF,"
        f"&H00000000,&HFF000000,0,0,0,0,100,100,0,0,1,{outline},0,2,20,20,{margin_v},1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    highlight_override = _highlight_override_ass(style, axis)
    for index, cue in enumerate(cues):
        placement = None
        if placements is not None and index < len(placements):
            placement = placements[index]
        # Feature A (§3.3): cues carrying word-level alignment emit N
        # contiguous highlighted lines; hand-built word-less cues keep
        # today's single plain line exactly.
        if cue.words:
            lines.extend(
                _highlighted_dialogue_lines(
                    cue,
                    highlight_override=highlight_override,
                    placement=placement,
                )
            )
        else:
            lines.append(_plain_dialogue_line(cue, placement=placement))

    return "\n".join(lines) + "\n"


def subtitles_filter_fragment(
    input_label: str, output_label: str, ass_path: Path, font_dir: Path
) -> str:
    """One `filter_complex` fragment: burns `ass_path`'s cues onto whatever
    video is at `input_label`, emitting `output_label`. Composed with the
    watermark's own fragment (if any) by `app/workflow/steps/render.py`
    into a single filter graph run through
    `app/renderer/video_filters.py::apply_video_filters` - captions no
    longer own their own ffmpeg invocation (docs/plans/
    watermark_implementation_plan.md §1: one re-encode, not one per
    filter)."""
    return (
        f"[{input_label}]subtitles=filename='{escape_ffmpeg_filter_path(ass_path)}':"
        f"fontsdir='{escape_ffmpeg_filter_path(font_dir)}'[{output_label}]"
    )
