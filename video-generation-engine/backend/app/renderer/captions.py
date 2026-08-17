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
from dataclasses import dataclass
from pathlib import Path

from app.models.narration import NarrationModel
from app.planners.fragments import split_narration_fragments
from app.renderer.video_filters import escape_ffmpeg_filter_path
from app.schemas.timeline import Timeline

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
class CaptionCue:
    start_s: float
    end_s: float
    text: str


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
    across a shot boundary, only within one."""
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

        for shot in scene.shots:
            if shot.narration_span is None:
                continue
            span_start, span_end = shot.narration_span
            if span_end <= span_start:
                continue
            for seg_start, seg_end in _segment_span(
                scene.narration_text,
                span_start,
                span_end,
                max_chars=max_chars,
                min_duration_s=min_duration_s,
                max_duration_s=max_duration_s,
                char_starts=char_starts,
                char_ends=char_ends,
            ):
                text = scene.narration_text[seg_start:seg_end].strip()
                if not text:
                    continue
                cues.append(
                    CaptionCue(
                        start_s=scene_offset_s + char_starts[seg_start],
                        end_s=scene_offset_s + char_ends[seg_end - 1],
                        text=text,
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
    re-narration with a different voice, and any segmentation-rule change
    in one value. Fixed precision, stable ordering - never
    locale-dependent float formatting."""
    digest_input = "|".join(f"{c.start_s:.3f},{c.end_s:.3f},{c.text}" for c in cues).encode()
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


def serialize_ass(cues: list[CaptionCue], style: CaptionStyle) -> str:
    """Pure. Fixed decimal precision, stable ordering, no `datetime.now()`
    or other non-deterministic content anywhere (I5, doc §5)."""
    width, height = style.resolution
    font_size = max(round(height * style.font_size_fraction), 1)
    outline = max(round(height * style.outline_fraction), 1)
    margin_v = max(round(height * style.margin_v_fraction), 0)

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
    for cue in cues:
        start = format_ass_time(cue.start_s)
        end = format_ass_time(cue.end_s)
        text = _escape_ass_text(cue.text)
        lines.append(f"Dialogue: 0,{start},{end},Caption,,0,0,0,,{text}")

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
