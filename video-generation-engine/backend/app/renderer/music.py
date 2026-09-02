"""Music mixing: the M8 step-4 ducking pass (D6/21.2).

A STATIC volume envelope, never a live sidechain compressor - I5
requires rendering to be a pure function of its inputs, and a real-time
compressor's behaviour depends on the actual sample stream in ways that
are not exactly reproducible the way a precomputed, timestamped envelope
is. The bed plays throughout at `MUSIC_BED_GAIN_DB`, ducked to
`MUSIC_DUCK_GAIN_DB` across every interval narration is speaking, with a
fade in/out at the video's boundaries.

## How the envelope is built without ffmpeg expression escaping

A `volume` filter's own expression mode (`volume='if(between(t,a,b),x,y)'`)
needs every comma inside the expression escaped for the surrounding
filtergraph syntax, which nests badly once there is more than one
interval. Instead: chain one `volume` filter per speaking interval, each
scoped with `enable='between(t,start,end)'` (ffmpeg's per-filter time
gate) to a RELATIVE gain of `duck_linear / bed_linear` - applied on top
of a base `volume=bed_linear` filter that runs unconditionally across
the whole stream. Outside every `enable` window each interval's filter
is a no-op (multiply by 1); inside one, the two multiply out to exactly
`duck_linear`. Deterministic, no nested expressions, and the chain is
built from a plain Python list of intervals in a fixed order (I5 - never
from unordered iteration).

## What "every interval narration is speaking" means here

OQ-1b (2026-08-28) + §15.1 (2026-08-29): when per-character alignment is
available, duck windows follow real speech runs on the audio-concat
clock — scene i starts at the sum of previous scenes' last
`character_end`.

ElevenLabs never leaves a gap *between* characters (measured: 0
inter-character gaps on six projects). The pauses live *inside* a
character's own duration — on `1cdf55ac`, 17 characters ≥0.30 s, all
newlines, longest 0.584 s. So a run splits when a character's OWN
duration exceeds `DUCK_CHAR_PAUSE_S` (0.30 s, the §13.4 counting
cutoff), not when `next_start - this_end` is large.
`DUCK_MERGE_THRESHOLD_S` (0.8 s, captions' min cue) is the wrong
quantity for this: every measured pause is below it, so using it as the
split would leave the detector inert. When the `characters` array is
present, only whitespace characters that long are pauses (a 0.4 s
spoken phoneme is not a bed swell). Inter-character gaps, if they ever
appear, still merge below 0.8 s.

Leading silence before the first character and trailing silence after a
scene's last character are NOT ducked. The long pause character itself
is NOT ducked — that is the swell. Ramps in/out of each duck are a
small number of stepped `between()` windows (not ffmpeg volume
expressions — see above), still a precomputed static envelope (I5; no
live sidechain).

When alignment is missing/None, fall back to per-SCENE granularity from
ffprobe-measured narration file durations (`compute_narration_intervals`),
exactly as before OQ-1b.

## Looping and length

The music input is read with `-stream_loop -1` (repeat indefinitely) and
then `atrim`med to the video's own real (ffprobe-measured) duration -
this covers a track shorter OR longer than the video with the same two
ffmpeg options, so no duration-based preference is needed when ranking
candidates (see `app/assets/music_ranking.py`).

## Ducking a second layer: diegetic SFX (A11, long_form_direction.md, 2026-09-01)

The bed used to duck against narration only. A diegetic cue (a church
bell, a Geiger counter) is a significant EFFECT, not background noise -
documentary sound conventionally lets it push the bed back too, just not
as far as narration does (it is a moment, not a floor). `mux_music`
accepts an optional second set of windows (`effect_intervals`) at their
own, shallower depth (`effect_duck_gain_db`); `combine_duck_windows`
merges them with the narration windows onto one envelope, in RELATIVE
gain terms, taking the DEEPER of the two wherever they overlap - two
`volume=` filters chained in series MULTIPLY where they overlap (see
`duck_ramp_windows`'s docstring), so ducking both depths at once would
not duck "a bit more", it would duck to their PRODUCT. When there are no
diegetic cues this whole path is skipped and `build_ducked_bed` runs
exactly as it always has - see `mux_music`'s own docstring.

## Two ffmpeg passes, not one, and why

`_build_ducked_bed` produces the ducked, faded, video-length music track
as its OWN file first; `mux_music` then does a second, simpler pass that
either maps that file straight through (no narration) or `amix`es it
with the video's existing narration stream. Splitting it this way keeps
the ducking envelope directly testable in isolation - measuring a mixed
narration+music signal cannot distinguish "the music got quieter" from
"narration is simply loud", which is exactly the failure a first-draft,
single-pass version of this module ran into while it was being built.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from app.core.logging import get_logger
from app.renderer.captions import MIN_CUE_DURATION_S
from app.renderer.slideshow import RenderSettings, probe_duration_seconds, run_ffmpeg

logger = get_logger(__name__)

_FADE_SECONDS = 1.0

# Inter-character GAP merge (OQ-1b). Captions' min cue duration — kept
# for the rare case ElevenLabs does leave a hole between characters.
# NOT the intra-character pause detector: §13.4 measured those at
# 0.30–0.584 s, all below 0.8 s.
DUCK_MERGE_THRESHOLD_S = MIN_CUE_DURATION_S  # 0.8 s

# Intra-character pause (§15.1 / §13.4). A character whose own
# duration exceeds this is a pause (on real EL data: newlines), and the
# bed is released for that window. 0.30 s is the cutoff the listen
# counted with; 0.8 s would miss every measured pause.
DUCK_CHAR_PAUSE_S = 0.30

# Starting ear default for duck in/out ramps — not signed off (OQ-1b).
DUCK_RAMP_S = 0.080
DUCK_RAMP_STEPS = 4


def offset_bed_and_duck_gain_db(
    bed_gain_db: float, duck_gain_db: float, gain_offset_db: float
) -> tuple[float, float]:
    """Applies the human's per-track dB offset (`gain_offset_db` - the
    BGM upload slider, analysis.md decision 7) to BOTH the bed and the
    duck gain, so the whole envelope shifts together and the style's duck
    DEPTH (`bed_gain_db - duck_gain_db`) is preserved.

    Analysis.md RV6: `_volume_chain` below computes
    `relative_duck = duck_linear / bed_linear` and applies that RATIO on
    top of an unconditional `volume=bed_linear` - which makes the level
    during a narration window resolve to the ABSOLUTE `duck_gain_db`,
    independent of the bed. Offsetting the bed alone therefore does not
    move the ducked floor at all; it only changes how far above that
    fixed floor the bed sits. Once the offset drops the bed below the
    duck gain (`gain_offset_db < duck_gain_db - bed_gain_db`, i.e. more
    negative than the style's own duck depth), `relative_duck` exceeds
    1.0 and ducking INVERTS - music gets LOUDER, not quieter, under
    narration. Applying the offset to both gains keeps `relative_duck`
    identical to the un-offset style mix for every offset value, so
    ducking can never invert."""
    return bed_gain_db + gain_offset_db, duck_gain_db + gain_offset_db


async def assemble_act_bed(
    segments: list[tuple[Path, float]],
    output_path: Path,
    settings: RenderSettings,
) -> Path:
    """Loop-and-trim each `(path, duration_s)` segment, then concat in
    order to `output_path`. One segment is still loop+trim so a short
    library track covers a 2-minute act the same way Path A's single bed
    covers the whole video. Hard cuts between acts — a 1.5–3 minute
    change does not need a crossfade, and a cut stays I5-simple."""
    if not segments:
        raise ValueError("assemble_act_bed requires at least one segment")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    work_dir = output_path.parent / f"_act_bed_{output_path.stem}"
    work_dir.mkdir(parents=True, exist_ok=True)
    trimmed: list[Path] = []
    for i, (path, duration_s) in enumerate(segments):
        piece = work_dir / f"act_{i:03d}.m4a"
        args = [
            settings.ffmpeg_binary,
            "-y",
            "-stream_loop",
            "-1",
            "-i",
            str(path),
            "-t",
            f"{duration_s:.3f}",
            "-c:a",
            "aac",
            "-fflags",
            "+bitexact",
            "-flags:a",
            "+bitexact",
            str(piece),
        ]
        await run_ffmpeg(args)
        trimmed.append(piece)

    if len(trimmed) == 1:
        trimmed[0].replace(output_path)
        return output_path

    list_path = work_dir / "concat.txt"
    list_path.write_text(
        "".join(f"file '{p.name}'\n" for p in trimmed),
        encoding="utf-8",
    )
    # `cwd=work_dir` below is what makes the BARE names inside concat.txt
    # (`act_000.m4a`, ...) resolve - the concat demuxer looks them up
    # relative to the process cwd, not to the list file. But that same cwd
    # change breaks every OTHER path in this argv if it is relative, and
    # `settings.storage_root` is relative (`'storage'`), so `list_path` and
    # `output_path` both are. ffmpeg then looked for
    # `work_dir/storage/<project>/work/_act_bed_.../concat.txt` and failed
    # with "No such file or directory" about a file sitting right there.
    #
    # Fixed 2026-09-02, on the first long-form project ever to reach a
    # render. Latent since per-act beds were built: `assemble_act_bed` only
    # runs on Path B (>70 narration fragments), and no Path B project had
    # got this far before - the picture rendered fine, then the whole draft
    # 400'd at the very last stage.
    #
    # `list_path.name` because the cwd IS `work_dir`; `output_path`
    # absolute because it is NOT under `work_dir`.
    args = [
        settings.ffmpeg_binary,
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        list_path.name,
        "-c",
        "copy",
        "-fflags",
        "+bitexact",
        str(output_path.resolve()),
    ]
    await run_ffmpeg(args, cwd=work_dir)
    return output_path


def _db_to_linear(gain_db: float) -> float:
    return 10 ** (gain_db / 20)


def speaking_intervals_from_alignment(
    alignment_by_scene: Sequence[Mapping[str, Any] | None],
    *,
    merge_threshold_s: float = DUCK_MERGE_THRESHOLD_S,
    char_pause_s: float = DUCK_CHAR_PAUSE_S,
) -> list[tuple[float, float]]:
    """Duck windows from per-character alignment on the audio-concat clock.

    Scene i starts at the sum of previous scenes' last `character_end`
    (same clock as OQ-0a silence map / `derive_caption_cues`).

    A run splits when a character's OWN duration exceeds `char_pause_s`
    (§15.1: ElevenLabs leaves no inter-character gaps; pauses live
    inside newline characters). That character is excluded from the duck
    window. Inter-character gaps ≤ `merge_threshold_s` still merge if
    they ever appear. Leading/trailing scene silence is not ducked.
    """
    parsed: list[tuple[list[float], list[float], list[str] | None] | None] = []
    for scene_index, alignment in enumerate(alignment_by_scene):
        parsed.append(_parse_scene_alignment(alignment, scene_index=scene_index))
    if any(scene is None for scene in parsed):
        # RV-Q2: one unusable scene used to leave scene_offset stuck, so
        # every later window sat on the wrong concat clock. Captions
        # refuse a row/scene mismatch outright; we do the same and let
        # mux_music fall back to file-duration intervals.
        logger.warning(
            "music.duck_alignment_abandoned",
            extra={
                "reason": "unusable_scene",
                "scenes": len(parsed),
                "unusable": sum(1 for scene in parsed if scene is None),
            },
        )
        return []

    intervals: list[tuple[float, float]] = []
    scene_offset = 0.0
    for local_starts, local_ends, local_chars in parsed:
        for start, end in _runs_from_characters(
            local_starts,
            local_ends,
            local_chars,
            char_pause_s=char_pause_s,
            merge_threshold_s=merge_threshold_s,
        ):
            intervals.append((scene_offset + start, scene_offset + end))
        scene_offset += local_ends[-1]

    return _merge_touching_intervals(intervals)


def _is_pause_character(
    duration_s: float,
    char: str | None,
    char_pause_s: float,
) -> bool:
    """True when this character is a bed-release, not speech.

    Duration-only when the `characters` array is absent. When present,
    only whitespace that long counts — a slow phoneme is not a pause.
    """
    if duration_s <= char_pause_s:
        return False
    if char is None:
        return True
    return char.isspace()


def _runs_from_characters(
    starts: list[float],
    ends: list[float],
    chars: list[str] | None,
    *,
    char_pause_s: float,
    merge_threshold_s: float,
) -> list[tuple[float, float]]:
    """Local (per-scene) duck windows. Pause characters are holes."""
    runs: list[tuple[float, float]] = []
    run_start: float | None = None
    run_end: float | None = None
    for i, (start, end) in enumerate(zip(starts, ends, strict=True)):
        ch = chars[i] if chars is not None else None
        if _is_pause_character(end - start, ch, char_pause_s):
            if run_start is not None and run_end is not None:
                runs.append((run_start, run_end))
                run_start = None
                run_end = None
            continue
        if run_start is None:
            run_start = start
            run_end = end
            continue
        gap = start - run_end
        if gap <= merge_threshold_s:
            run_end = end
        else:
            runs.append((run_start, run_end))
            run_start = start
            run_end = end
    if run_start is not None and run_end is not None:
        runs.append((run_start, run_end))
    return runs


def _parse_scene_alignment(
    alignment: Mapping[str, Any] | None,
    *,
    scene_index: int,
) -> tuple[list[float], list[float], list[str] | None] | None:
    if alignment is None:
        logger.warning(
            "music.duck_alignment_skipped",
            extra={"scene_index": scene_index, "reason": "alignment is None"},
        )
        return None
    starts_raw = list(alignment.get("character_start_times_seconds") or [])
    ends_raw = list(alignment.get("character_end_times_seconds") or [])
    if not starts_raw or not ends_raw or len(starts_raw) != len(ends_raw):
        logger.warning(
            "music.duck_alignment_skipped",
            extra={
                "scene_index": scene_index,
                "reason": "empty_or_length_mismatch",
                "n_starts": len(starts_raw),
                "n_ends": len(ends_raw),
            },
        )
        return None
    try:
        starts = [float(x) for x in starts_raw]
        ends = [float(x) for x in ends_raw]
    except (TypeError, ValueError):
        logger.warning(
            "music.duck_alignment_skipped",
            extra={"scene_index": scene_index, "reason": "non_numeric_times"},
        )
        return None
    chars_raw = alignment.get("characters")
    chars: list[str] | None = None
    if isinstance(chars_raw, list) and len(chars_raw) == len(starts):
        chars = [str(c) if c is not None else "" for c in chars_raw]
    return starts, ends, chars


def _merge_touching_intervals(
    intervals: list[tuple[float, float]],
    *,
    min_gap_s: float | None = None,
) -> list[tuple[float, float]]:
    """Collapse runs closer than 2*ramp so in/out ramps cannot overlap.

    RV-Q3: a 20–80 ms gap at a scene join is ordinary TTS leading
    silence; ramps of 80 ms on each side would multiply below the duck
    floor. Merging anything closer than two ramps removes the collision.
    """
    if not intervals:
        return []
    gap = 2 * DUCK_RAMP_S if min_gap_s is None else min_gap_s
    ordered = sorted(intervals)
    merged: list[tuple[float, float]] = [ordered[0]]
    for start, end in ordered[1:]:
        prev_start, prev_end = merged[-1]
        if start <= prev_end + gap:
            merged[-1] = (prev_start, max(prev_end, end))
        else:
            merged.append((start, end))
    return merged


def duck_envelope_content_hash(
    intervals: list[tuple[float, float]],
    *,
    merge_threshold_s: float = DUCK_MERGE_THRESHOLD_S,
    char_pause_s: float = DUCK_CHAR_PAUSE_S,
    ramp_s: float = DUCK_RAMP_S,
) -> str:
    """Fingerprint input for the alignment-derived duck envelope (OQ-1b).

    Hashes the canonical `(start, end)` duck windows plus merge/ramp/
    char-pause constants. When alignment is absent the render step
    passes `None` instead (file-duration fallback is fully determined by
    `narration_content_hashes`).
    """
    payload = {
        "intervals": [[round(start, 3), round(end, 3)] for start, end in intervals],
        "merge_threshold_s": merge_threshold_s,
        "char_pause_s": char_pause_s,
        "ramp_s": ramp_s,
        "ramp_steps": DUCK_RAMP_STEPS,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def duck_ramp_windows(
    intervals: list[tuple[float, float]],
    *,
    relative_duck: float,
    ramp_s: float = DUCK_RAMP_S,
    steps: int = DUCK_RAMP_STEPS,
) -> list[tuple[float, float, float]]:
    """Expand each duck into ramp-in steps + full duck + ramp-out steps.

    Returns `(start, end, relative_gain)` triples in chronological order
    per input interval. Relative gain is the multiplier applied on top of
    the unconditional bed `volume=` (same architecture as a flat duck).
    80 ms / 4 steps is the OQ-1b starting ear default — not signed off.

    ⚠ RV-Q3 (reopened 2026-08-29): these windows become `volume=` filters
    chained in series, so any two that overlap MULTIPLY. Correctness
    therefore depends on the input intervals being at least `2*ramp_s`
    apart, and that invariant is enforced HERE rather than left to the
    caller — the first fix put the guard only in
    `speaking_intervals_from_alignment`, and `compute_narration_intervals`
    (the fallback RV-Q2's own refusal routes into) returns per-scene
    intervals explicitly "back to back with no gap". Measured on that
    path before this guard: at a scene join both full ducks and both ramp
    sets were live at once, multiplying to **16.1 dB below the intended
    duck floor** for ~80 ms — an audible hole at every boundary, on a bed
    already sitting at −28 dB. Merging here is idempotent for the
    alignment path (already merged at the same threshold), so it changes
    no already-correct output and no fingerprint.
    """
    if ramp_s <= 0 or steps < 1:
        return [(start, end, relative_duck) for start, end in intervals]

    intervals = _merge_touching_intervals(intervals, min_gap_s=2 * ramp_s)
    # A11: delegates to the per-segment generalisation below so the two
    # can never drift apart - this is the single-depth case of that
    # function (every interval tagged with the same `relative_duck`),
    # not a second implementation of the same ramp math.
    return duck_ramp_windows_segments(
        [(start, end, relative_duck) for start, end in intervals],
        ramp_s=ramp_s,
        steps=steps,
    )


def combine_duck_windows(
    narration_intervals: list[tuple[float, float]],
    narration_duck_gain_db: float,
    effect_intervals: list[tuple[float, float]],
    effect_duck_gain_db: float,
    *,
    bed_gain_db: float,
) -> list[tuple[float, float, float]]:
    """A11 (long_form_direction.md, 2026-09-01): merge narration duck
    windows and diegetic-cue duck windows onto ONE envelope, in RELATIVE
    gain terms (mirrors `_volume_chain`'s own `duck_linear / bed_linear`
    math) so the result can go straight into `duck_ramp_windows_segments`.

    Where a cue window overlaps a narration window (a bell tolling mid-
    sentence), the DEEPER (quieter, i.e. lower relative gain) of the two
    wins for the whole overlap - two `volume=` filters chained in series
    MULTIPLY where they overlap (see `duck_ramp_windows`'s own docstring
    on RV-Q3), so ducking BOTH depths at once would not "duck a bit more",
    it would duck to their PRODUCT - audibly mud, and unbounded as more
    layers are added. "Deeper wins" is a ceiling, not a sum: the sweep
    below picks ONE depth per instant, never stacks two.

    A cue with no narration overlap plays at its own (shallower) depth; a
    narration window with no cue overlap is completely unaffected - this
    function returns exactly `narration_intervals` at
    `narration_duck_gain_db` (before ramping) when `effect_intervals` is
    empty, so the no-diegetic-cues path (every project today) is
    unchanged by this function's mere existence.

    Only SAME-depth neighbours closer than `2*DUCK_RAMP_S` are merged
    here (mirrors `_merge_touching_intervals` exactly, generalised to
    gain-tagged pieces) - e.g. a narration window and a slightly earlier-
    starting effect window that happen to end up at the identical relative
    gain once picked by the sweep. DIFFERENT-depth neighbours are left as
    separate segments on purpose: merging them into one flat block would
    also flatten whatever came BEFORE/AFTER at the OTHER depth the moment
    two windows touch (e.g. a nested 3s effect window inside a 60s
    narration span would otherwise duck the entire 60s to the effect's
    depth, not just the 3s it actually covers). `duck_ramp_windows_segments`
    handles the different-depth case instead, with a short crossfade AT
    the junction rather than a merge of the surrounding content.
    """
    tagged: list[tuple[float, float, float]] = []
    narr_rel = _db_to_linear(narration_duck_gain_db) / _db_to_linear(bed_gain_db)
    eff_rel = _db_to_linear(effect_duck_gain_db) / _db_to_linear(bed_gain_db)
    tagged += [(start, end, narr_rel) for start, end in narration_intervals if end > start]
    tagged += [(start, end, eff_rel) for start, end in effect_intervals if end > start]
    if not tagged:
        return []

    points = sorted({p for start, end, _ in tagged for p in (start, end)})
    segments: list[tuple[float, float, float]] = []
    # `strict=False` is deliberate, not laziness: `points[1:]` is one
    # shorter than `points` by construction - this is a pairwise walk over
    # consecutive boundaries, so the final unpaired point has nothing to
    # pair with and must be dropped.
    for a, b in zip(points, points[1:], strict=False):
        if b <= a:
            continue
        mid = (a + b) / 2
        active = [gain for start, end, gain in tagged if start <= mid < end]
        if not active:
            continue
        segments.append((a, b, min(active)))  # deeper duck = lower relative gain

    merge_gap = 2 * DUCK_RAMP_S
    merged: list[tuple[float, float, float]] = []
    for seg in segments:
        if merged:
            prev_start, prev_end, prev_gain = merged[-1]
            same_depth = abs(prev_gain - seg[2]) < 1e-9
            if same_depth and seg[0] - prev_end <= merge_gap:
                merged[-1] = (prev_start, max(prev_end, seg[1]), prev_gain)
                continue
        merged.append(seg)
    return merged


def duck_ramp_windows_segments(
    segments: list[tuple[float, float, float]],
    *,
    ramp_s: float = DUCK_RAMP_S,
    steps: int = DUCK_RAMP_STEPS,
) -> list[tuple[float, float, float]]:
    """Same ramp shape as `duck_ramp_windows`, generalised to a per-
    segment target gain (A11: narration and diegetic-cue windows can
    carry two different depths after `combine_duck_windows`).

    Each segment ramps in from the BED (1.0) and out to the BED exactly
    as `duck_ramp_windows` always has - UNLESS its neighbour sits within
    `2*ramp_s` (RV-Q3's own collision distance), in which case a short
    CROSSFADE directly between the two segments' own gains, occupying
    EXACTLY the gap between them (never wider - never reaching back into
    either segment's own flat body, so it cannot overlap and multiply
    with either one), replaces both that ramp-out and the neighbour's
    ramp-in. Two independent ramps back toward 1.0 and away from it
    again, occupying overlapping time, would both multiply AND produce
    an audible blip toward full bed volume between two ducks that are
    effectively touching - the crossfade removes both problems by
    transitioning duck-depth-to-duck-depth directly. When the gap is
    exactly zero (the common case: `combine_duck_windows`'s own sweep
    always produces touching boundaries at a genuine overlap, e.g. a cue
    mid-narration), the crossfade degenerates to nothing and the two
    segments simply meet with a direct step in gain at one shared
    instant - not a ramp collision, since neither segment's window
    extends past that shared point. Only the junction is affected; each
    segment's own flat body (`(start, end, gain)`) is always emitted
    unchanged, so unlike a merge this cannot flatten unrelated content on
    either side of a short nested window (see `combine_duck_windows`'s
    own docstring for why that matters).

    For the single-depth caller (`duck_ramp_windows`, which pre-merges
    close intervals via `_merge_touching_intervals` before tagging them),
    no two segments are ever within `2*ramp_s` of each other by the time
    they reach this function, so the crossfade branch never fires there -
    this is exactly `duck_ramp_windows`'s pre-A11 behaviour, unchanged.
    """
    if ramp_s <= 0 or steps < 1:
        return list(segments)

    ordered = [seg for seg in sorted(segments, key=lambda item: item[0]) if seg[1] > seg[0]]
    n = len(ordered)
    windows: list[tuple[float, float, float]] = []
    dt = ramp_s / steps

    for i, (start, end, gain) in enumerate(ordered):
        prev = ordered[i - 1] if i > 0 else None
        gap_prev = (start - prev[1]) if prev is not None else None
        junction_in = gap_prev is not None and gap_prev <= 2 * ramp_s
        if not junction_in:
            for k in range(1, steps + 1):
                t0 = start - ramp_s + (k - 1) * dt
                t1 = start - ramp_s + k * dt
                g = 1.0 + (gain - 1.0) * (k / steps)
                if t1 <= 0 or t1 <= t0:
                    continue
                windows.append((max(t0, 0.0), t1, g))
        # else: this ramp-in was already emitted as the PREVIOUS
        # segment's junction crossfade below - never emit both sides.

        windows.append((start, end, gain))

        nxt = ordered[i + 1] if i + 1 < n else None
        gap_next = (nxt[0] - end) if nxt is not None else None
        junction_out = gap_next is not None and gap_next <= 2 * ramp_s
        if junction_out:
            assert nxt is not None and gap_next is not None
            gap = max(gap_next, 0.0)
            step_w = gap / steps
            for k in range(steps):
                t0 = end + k * step_w
                t1 = end + (k + 1) * step_w
                frac = (k + 1) / steps
                g = gain + (nxt[2] - gain) * frac
                if t1 <= t0:
                    continue
                windows.append((t0, t1, g))
        else:
            for k in range(1, steps + 1):
                t0 = end + (k - 1) * dt
                t1 = end + k * dt
                g = gain + (1.0 - gain) * (k / steps)
                if t1 <= t0:
                    continue
                if abs(g - 1.0) < 1e-12:
                    continue
                windows.append((t0, t1, g))

    windows.sort(key=lambda item: (item[0], item[1]))
    return windows


async def compute_narration_intervals(
    narration_paths: list[Path], ffprobe_binary: str
) -> list[tuple[float, float]]:
    """`[(start, end), ...]` in the FINAL, muxed narration track's own
    time base - one interval per scene, back to back with no gap,
    matching exactly how `mux_narration`'s concat FILTER joins them (real
    decoded durations, never an encoder-framed estimate - see that
    module's own docstring on why the concat DEMUXER's duration would be
    wrong here)."""
    intervals: list[tuple[float, float]] = []
    cursor = 0.0
    for path in narration_paths:
        duration = await probe_duration_seconds(path, ffprobe_binary)
        intervals.append((cursor, cursor + duration))
        cursor += duration
    return intervals


def _volume_chain_segments(segments: list[tuple[float, float, float]], *, bed_gain_db: float) -> str:
    bed_linear = _db_to_linear(bed_gain_db)
    filters = [f"volume={bed_linear:.6f}"]
    for start, end, rel in segments:
        # A single `between(t,a,b)` per filter - the escaped comma is
        # the only one, never nested inside a broader if()/expression.
        filters.append(f"volume={rel:.6f}:enable='between(t\\,{start:.3f}\\,{end:.3f})'")
    return ",".join(filters)


def _volume_chain(
    intervals: list[tuple[float, float]], *, bed_gain_db: float, duck_gain_db: float
) -> str:
    bed_linear = _db_to_linear(bed_gain_db)
    duck_linear = _db_to_linear(duck_gain_db)
    relative_duck = duck_linear / bed_linear
    # A11: same single-depth case of `_volume_chain_segments` that
    # `duck_ramp_windows` is of `duck_ramp_windows_segments` - kept as
    # its own function (rather than inlined at every call site) since
    # `bed_gain_db`/`duck_gain_db` is still the common, single-depth call
    # shape everywhere except the diegetic-duck path in `mux_music`.
    return _volume_chain_segments(
        duck_ramp_windows(intervals, relative_duck=relative_duck), bed_gain_db=bed_gain_db
    )


async def build_ducked_bed_segments(
    music_path: Path,
    video_duration: float,
    segments: list[tuple[float, float, float]],
    output_path: Path,
    settings: RenderSettings,
    *,
    bed_gain_db: float,
) -> Path:
    """Same as `build_ducked_bed`, but `segments` are already fully
    resolved, ramped `(start, end, relative_gain)` triples (A11: the
    narration-window depth and the diegetic-cue-window depth can differ,
    so there is no single `duck_gain_db` left to pass here - see
    `combine_duck_windows`/`duck_ramp_windows_segments`, which is what
    `mux_music` calls before handing the result to this function)."""
    fade_seconds = min(_FADE_SECONDS, video_duration / 2)
    fade_out_start = max(video_duration - fade_seconds, 0.0)
    chain = _volume_chain_segments(segments, bed_gain_db=bed_gain_db)

    args = [
        settings.ffmpeg_binary,
        "-y",
        "-stream_loop",
        "-1",
        "-i",
        str(music_path),
        "-filter_complex",
        f"[0:a]atrim=0:{video_duration:.3f},asetpts=PTS-STARTPTS,{chain},"
        f"afade=t=in:st=0:d={fade_seconds:.3f},"
        f"afade=t=out:st={fade_out_start:.3f}:d={fade_seconds:.3f}[aout]",
        "-map",
        "[aout]",
        "-c:a",
        "aac",
        # I5 (M8 step 6): see app/renderer/slideshow.py's own comment on
        # this exact pair - strips non-deterministic muxer/encoder
        # metadata from the (intermediate) ducked-bed file too, so the
        # final mux downstream is reproducible from identical inputs.
        "-fflags",
        "+bitexact",
        "-flags:a",
        "+bitexact",
        str(output_path),
    ]
    await run_ffmpeg(args)
    return output_path


async def build_ducked_bed(
    music_path: Path,
    video_duration: float,
    intervals: list[tuple[float, float]],
    output_path: Path,
    settings: RenderSettings,
    *,
    bed_gain_db: float,
    duck_gain_db: float,
) -> Path:
    """The music bed alone (looped/trimmed to `video_duration`, ducked
    across `intervals`, faded in/out at the boundaries) - no video, no
    narration, an audio-only file. Directly testable in isolation (see
    tests/integration/test_render_music_mix.py) precisely because nothing
    else is mixed into it yet.

    A11: the single-depth case of `build_ducked_bed_segments` (kept under
    its original name/signature so every existing narration-only caller
    and test is untouched byte-for-byte)."""
    bed_linear = _db_to_linear(bed_gain_db)
    duck_linear = _db_to_linear(duck_gain_db)
    relative_duck = duck_linear / bed_linear
    segments = duck_ramp_windows(intervals, relative_duck=relative_duck)
    return await build_ducked_bed_segments(
        music_path, video_duration, segments, output_path, settings, bed_gain_db=bed_gain_db
    )


async def mux_music(
    video_path: Path,
    music_path: Path,
    narration_paths: list[Path] | None,
    output_path: Path,
    settings: RenderSettings,
    *,
    bed_gain_db: float,
    duck_gain_db: float,
    amix_normalize: int = 0,
    alignment_by_scene: Sequence[Mapping[str, Any] | None] | None = None,
    effect_intervals: list[tuple[float, float]] | None = None,
    effect_duck_gain_db: float | None = None,
) -> Path:
    """Mixes `music_path` (looped/trimmed to `video_path`'s real length,
    ducked under `narration_paths` if any) onto `video_path`, writing
    `output_path`. `video_path`'s own existing streams are copied through
    unchanged (`-c:v copy`); when it already carries a narration audio
    stream (`narration_paths` not empty/None), that stream is mixed with
    the ducked bed via `amix` - when it doesn't (no narration, or
    DRY_RUN's caller never gets here at all - see
    `RenderStep._resolve_music_track`), the ducked bed becomes the
    output's only audio stream.

    `amix_normalize` is the ffmpeg `amix` normalize flag (OQ-1d). 0 keeps
    narration at the same level with or without a bed; 1 is ffmpeg's
    default (scale 1/n). The render step fingerprints the same value
    (RV2).

    `alignment_by_scene` (OQ-1b): when provided, duck windows come from
    `speaking_intervals_from_alignment`; otherwise file-duration
    per-scene intervals (`compute_narration_intervals`).

    `effect_intervals`/`effect_duck_gain_db` (A11, long_form_direction.md,
    2026-09-01): diegetic-cue duck windows, computed by the caller from
    the TIMELINE (shot start times + the cue clip's persisted duration),
    never from the SFX audio itself - `render_video`'s own pipeline order
    is narration -> music -> sfx, so the SFX files do not exist yet at
    this point. When present, narration and cue windows are combined onto
    one envelope via `combine_duck_windows` (deeper duck wins on overlap,
    never both multiplied); when absent/empty (every project with no
    `Shot.sfx_cue`, i.e. the overwhelming majority today), this function's
    behaviour is completely unchanged from before this parameter existed
    - `build_ducked_bed` is called exactly as it always was.
    """
    video_duration = await probe_duration_seconds(video_path, settings.ffprobe_binary)
    if alignment_by_scene is not None:
        intervals = speaking_intervals_from_alignment(alignment_by_scene)
        source = "alignment"
        if not intervals and narration_paths:
            # Alignment present but produced no windows (all scenes
            # malformed) — do not leave the bed unducked under speech.
            intervals = await compute_narration_intervals(
                narration_paths, settings.ffprobe_binary
            )
            source = "file_duration_fallback"
    elif narration_paths:
        intervals = await compute_narration_intervals(narration_paths, settings.ffprobe_binary)
        source = "file_duration"
    else:
        intervals = []
        source = "none"

    logger.info(
        "music.duck_envelope",
        extra={
            "source": source,
            "interval_count": len(intervals),
            "merge_threshold_s": DUCK_MERGE_THRESHOLD_S,
            "char_pause_s": DUCK_CHAR_PAUSE_S,
            "ramp_s": DUCK_RAMP_S,
            "ramp_steps": DUCK_RAMP_STEPS,
        },
    )

    ducked_bed_path = output_path.parent / f"_ducked_bed_{output_path.stem}.m4a"
    if effect_intervals:
        # A11: at least one diegetic cue - combine onto one envelope
        # rather than calling `build_ducked_bed` (which only knows a
        # single depth) at all.
        resolved_effect_duck_gain_db = (
            effect_duck_gain_db if effect_duck_gain_db is not None else duck_gain_db
        )
        combined = combine_duck_windows(
            intervals,
            duck_gain_db,
            effect_intervals,
            resolved_effect_duck_gain_db,
            bed_gain_db=bed_gain_db,
        )
        segments = duck_ramp_windows_segments(combined)
        logger.info(
            "music.diegetic_duck_windows",
            extra={
                "effect_interval_count": len(effect_intervals),
                "effect_duck_gain_db": resolved_effect_duck_gain_db,
                "combined_segment_count": len(segments),
            },
        )
        await build_ducked_bed_segments(
            music_path,
            video_duration,
            segments,
            ducked_bed_path,
            settings,
            bed_gain_db=bed_gain_db,
        )
    else:
        await build_ducked_bed(
            music_path,
            video_duration,
            intervals,
            ducked_bed_path,
            settings,
            bed_gain_db=bed_gain_db,
            duck_gain_db=duck_gain_db,
        )

    args = [
        settings.ffmpeg_binary,
        "-y",
        "-i",
        str(video_path),
        "-i",
        str(ducked_bed_path),
    ]

    has_narration_audio = bool(narration_paths)
    if has_narration_audio:
        # `duration=longest`, not `first` (a first draft used `first`
        # and it was wrong): the ducked bed is already trimmed to the
        # VIDEO's own length, but narration's own real length can be a
        # hair shorter (rounding - `mux_narration` never pads it) or, in
        # theory, a test double could hand this function a mismatched
        # pair. `first` would silently truncate the whole mixed output
        # to narration's length the moment it is even slightly shorter
        # than the video/music - `longest` is the only option that
        # cannot truncate a real track early.
        args += [
            "-filter_complex",
            # Default ffmpeg normalize=1 scales each active input by 1/n
            # (~−6 dB with two inputs). Same flag as mux_sfx (RV11).
            f"[0:a][1:a]amix=inputs=2:duration=longest:dropout_transition=0:"
            f"normalize={int(amix_normalize)}[aout]",
            "-map",
            "0:v",
            "-map",
            "[aout]",
        ]
    else:
        args += ["-map", "0:v", "-map", "1:a"]

    args += [
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-fflags",
        "+bitexact",
        "-flags:a",
        "+bitexact",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    await run_ffmpeg(args)
    return output_path
