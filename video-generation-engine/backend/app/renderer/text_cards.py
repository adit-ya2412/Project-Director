"""Text cards (motion_new_styles_and_long_form_videos.md §2.6, Tier 2,
2026-08-17): a structural title/heading overlay for a SHOT, never
dialogue captions - those come from real narration timing (D2) and stay
entirely separate (`app/renderer/captions.py`). Deliberately its own
small module rather than folded into `captions.py`: the two overlays
answer different questions (this shot's on-screen presence vs. what is
being said right now), use a genuinely different escaping rule (a card
preserves an author's own line breaks; a caption collapses them, since a
caption is a fragment of continuous speech), and a different ASS style
(centered, larger, fading) - reusing `captions.py`'s `CaptionCue`/
`CaptionStyle` would mean bending both to fit a second, different
purpose. `format_ass_time` IS shared (pure time formatting, no
caption-specific logic to duplicate - S2 precedent).

## Scope, stated plainly (plan §2.6)

Static text, simple fade in/out - NOT kinetic typography. ASS/`drawtext`
give timed reveals and animated cards, not a directed title sequence;
this module does the honest version of that, not a half-built attempt
at the dishonest one.

## Timing: the RENDERED-timeline clock, not narration

A card is tied to which SHOT is on screen, not to spoken words - so its
window is `compute_shot_start_times`'s own [start, start + duration_s)
for that shot (D5's overlap arithmetic, the same clock the renderer
itself uses), never narration alignment. This also means a text card
works even on a silent render (DRY_RUN, or a Timeline with no narration
yet) - captions cannot make that claim, since they require resolved
narration rows to exist at all.
"""

import hashlib
from dataclasses import dataclass
from pathlib import Path

from app.renderer.captions import format_ass_time
from app.renderer.video_filters import escape_ffmpeg_filter_path
from app.schemas.timeline import Timeline
from app.timeline.duration import compute_shot_start_times

# Fixed, not planner-controlled (plan's own "minimal" scope) - a single
# knob here would be one more thing every style/prompt would need to
# reason about for a v1 feature. Revisit if a real render ever needs a
# different feel.
_FADE_IN_S = 0.5
_FADE_OUT_S = 0.5


@dataclass(frozen=True)
class TextCardCue:
    start_s: float
    end_s: float
    text: str


@dataclass(frozen=True)
class TextCardStyle:
    resolution: tuple[int, int]
    font_family: str
    # Larger than a caption's 0.045 (`CaptionStyle`) - a title card is
    # meant to read as a heading, not a subtitle.
    font_size_fraction: float = 0.075


def derive_text_card_cues(timeline: Timeline) -> list[TextCardCue]:
    """One cue per shot with a non-empty `text_card`, in the shot's own
    rendered on-screen window. Pure - no database, no narration rows
    required (see module docstring)."""
    shots = timeline.all_shots()
    starts = compute_shot_start_times(shots)
    cues: list[TextCardCue] = []
    for shot in shots:
        text = (shot.text_card or "").strip()
        if not text:
            continue
        start_s = starts[shot.id]
        cues.append(TextCardCue(start_s=start_s, end_s=start_s + shot.duration_s, text=text))
    return cues


def text_card_content_hash(cues: list[TextCardCue]) -> str:
    """Mirrors `captions.py::cue_list_content_hash` exactly - part of the
    render fingerprint (I5), same reasoning: a text-card change must
    invalidate the cache, never silently serve an old card (or no card)
    forever."""
    digest_input = "\x1f".join(
        f"{c.start_s:.3f}\x1e{c.end_s:.3f}\x1e{c.text}" for c in cues
    ).encode("utf-8")
    return hashlib.sha256(digest_input).hexdigest()


def _escape_text_card_text(text: str) -> str:
    """Deliberately NOT `captions.py::_escape_ass_text` - a card
    preserves the author's own line breaks (`\\N`, ASS's hard line-break
    override) rather than collapsing them to a space. A two-line title
    card is a normal, deliberate choice; a caption is a fragment of
    continuous speech, where a real newline never carries meaning."""
    text = text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")
    return text.replace("\r\n", "\\N").replace("\n", "\\N").replace("\r", "\\N")


def serialize_text_card_ass(cues: list[TextCardCue], style: TextCardStyle) -> str:
    """Pure, fixed decimal precision, no non-deterministic content (I5) -
    same discipline as `captions.py::serialize_ass`. A SEPARATE ASS file
    from captions, burned as a second `subtitles=` fragment in the same
    filter_complex pass (no second re-encode - `app/workflow/steps/
    render.py` composes both, plus the grade and the watermark, into one
    filter graph)."""
    width, height = style.resolution
    font_size = max(round(height * style.font_size_fraction), 1)
    fade_in_ms = round(_FADE_IN_S * 1000)
    fade_out_ms = round(_FADE_OUT_S * 1000)

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
        # Alignment=5: middle-center (ASS numpad convention) - a title
        # card is centered on the frame, unlike a caption's bottom-center
        # (Alignment=2, captions.py). Bold=-1 (ASS true), white on a
        # heavy black outline, no filled background box.
        f"Style: TextCard,{style.font_family},{font_size},&H00FFFFFF,&H00FFFFFF,"
        f"&H00000000,&HFF000000,-1,0,0,0,100,100,0,0,1,{max(round(font_size * 0.08), 1)},0,5,40,40,40,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    for cue in cues:
        start = format_ass_time(cue.start_s)
        end = format_ass_time(cue.end_s)
        # Fade clamped to at most half the cue's own duration - a very
        # short shot still gets a graceful (if brief) fade rather than an
        # invalid or all-fade, no-hold result.
        duration_ms = max(round((cue.end_s - cue.start_s) * 1000), 1)
        clamped_in = min(fade_in_ms, duration_ms // 2)
        clamped_out = min(fade_out_ms, duration_ms // 2)
        text = "{\\fad(" + f"{clamped_in},{clamped_out}" + ")}" + _escape_text_card_text(cue.text)
        lines.append(f"Dialogue: 0,{start},{end},TextCard,,0,0,0,,{text}")

    return "\n".join(lines) + "\n"


def text_card_filter_fragment(
    input_label: str, output_label: str, ass_path: Path, font_dir: Path
) -> str:
    """One `filter_complex` fragment - identical shape to `captions.py::
    subtitles_filter_fragment`, a second `subtitles=` call chained in the
    same pass rather than a second ffmpeg invocation."""
    return (
        f"[{input_label}]subtitles=filename='{escape_ffmpeg_filter_path(ass_path)}':"
        f"fontsdir='{escape_ffmpeg_filter_path(font_dir)}'[{output_label}]"
    )
