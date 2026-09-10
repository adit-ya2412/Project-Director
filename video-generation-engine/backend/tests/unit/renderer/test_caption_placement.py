"""K17 content-aware caption placement — unit tests, no ffmpeg."""

from __future__ import annotations

import inspect
from dataclasses import replace
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from app.renderer.caption_placement import (
    CANDIDATE_BOXES,
    CandidateBox,
    CaptionPlacement,
    apply_caption_placements,
    boxes_overlap,
    caption_placement_content_hash,
    scale_candidate,
)
from app.renderer.captions import CaptionCue, CaptionStyle, CaptionWord, serialize_ass
from app.renderer.compositor import OverlayCue, stamp_band
from app.schemas.timeline import (
    Camera,
    CameraMovement,
    Shot,
    ShotIntent,
    Transition,
    TransitionType,
)
from app.timeline.duration import compute_shot_start_times, compute_timeline_duration


def _shot(shot_id: str = "sh_01", *, duration_s: float = 5.0) -> Shot:
    return Shot(
        id=shot_id,
        order=0,
        intent=ShotIntent.EXPLAIN,
        duration_s=duration_s,
        prompt="plate",
        camera=Camera(movement=CameraMovement.STATIC),
    )


def _cue(start_s: float = 0.5, end_s: float = 1.5, text: str = "hello") -> CaptionCue:
    return CaptionCue(start_s=start_s, end_s=end_s, text=text)


def _stamp_overlay(
    *,
    start_frame: int = 0,
    end_frame: int = 60,
    top_fraction: float = 0.18,
    width: int = 720,
    height: int = 1280,
) -> OverlayCue:
    band = stamp_band(
        width,
        height,
        text="लाखों लोग",
        text_register="hi",
        top_fraction=top_fraction,
    )
    return OverlayCue(
        device="stamp",
        text="लाखों लोग",
        text_register="hi",
        offset_s=0.0,
        start_frame=start_frame,
        end_frame=end_frame,
        shot_id="sh_01",
        band=band,
    )


def _uniform_plate(tmp_path: Path, colour: tuple[int, int, int] = (128, 128, 128)) -> Path:
    path = tmp_path / "plate.png"
    Image.new("RGB", (720, 1280), color=colour).save(path, format="PNG")
    return path


# ---------------------------------------------------------------------------
# K17.2 occupancy
# ---------------------------------------------------------------------------


def test_live_stamp_band_excludes_upper_centre(tmp_path: Path):
    """frame_C_0.55.png collision: stamp at top 0.18 knocks out upper-centre."""
    plate = _uniform_plate(tmp_path)
    stamp = _stamp_overlay(top_fraction=0.18)
    upper = scale_candidate(CANDIDATE_BOXES[2], canvas_width=720, canvas_height=1280)
    assert stamp.band is not None
    band_box = stamp.band.box_on(720, 1280)
    assert band_box is not None
    assert boxes_overlap(upper.box, band_box)

    out = apply_caption_placements(
        [_cue(0.5, 1.5)],
        {"sh_01": plate},
        [stamp],
        shots=[_shot()],
        canvas_width=720,
        canvas_height=1280,
        fps=30,
    )
    assert out[0] is not None
    assert out[0].name != "upper-centre"


def test_overlay_without_band_does_not_occupy(tmp_path: Path):
    plate = _uniform_plate(tmp_path)
    bare = OverlayCue(
        device="stamp",
        text="x",
        text_register="en",
        offset_s=0.0,
        start_frame=0,
        end_frame=60,
        shot_id="sh_01",
        band=None,
    )
    # Uniform plate → all three tie on busyness → table order → bottom-centre.
    out = apply_caption_placements(
        [_cue()],
        {"sh_01": plate},
        [bare],
        shots=[_shot()],
        canvas_width=720,
        canvas_height=1280,
        fps=30,
    )
    assert out[0] is not None
    assert out[0].name == "bottom-centre"


# ---------------------------------------------------------------------------
# K17.3 variance beats mean
# ---------------------------------------------------------------------------


def _checkerboard(size: tuple[int, int], a: tuple[int, int, int], b: tuple[int, int, int], cell: int = 8) -> Image.Image:
    w, h = size
    img = Image.new("RGB", size, color=a)
    draw = ImageDraw.Draw(img)
    for y in range(0, h, cell):
        for x in range(0, w, cell):
            if ((x // cell) + (y // cell)) % 2 == 0:
                draw.rectangle((x, y, min(x + cell - 1, w - 1), min(y + cell - 1, h - 1)), fill=b)
    return img


def test_variance_beats_mean_busy_bright_loses_to_calm_mid(tmp_path: Path):
    """Busy-bright (high mean, high variance) loses to calm-mid (medium mean, low variance)."""
    width, height = 720, 1280
    image = Image.new("RGB", (width, height), color=(40, 40, 40))
    y0, y1 = round(0.72 * height), round(0.88 * height)
    # Bottom strip: busy-bright checkerboard across the full width first.
    busy = _checkerboard((width, y1 - y0), (200, 200, 200), (255, 255, 255), cell=8)
    image.paste(busy, (0, y0))
    # Bottom-left (0–0.7W): overwrite with flat mid grey — low variance.
    x1 = round(0.7 * width)
    ImageDraw.Draw(image).rectangle((0, y0, x1 - 1, y1 - 1), fill=(128, 128, 128))
    # Upper-centre: high-contrast checkerboard so it cannot win on variance.
    uy0, uy1 = round(0.22 * height), round(0.38 * height)
    upper = _checkerboard((width, uy1 - uy0), (0, 0, 0), (255, 255, 255), cell=6)
    image.paste(upper, (0, uy0))

    plate = tmp_path / "variance.png"
    image.save(plate, format="PNG")
    out = apply_caption_placements(
        [_cue()],
        {"sh_01": plate},
        [],
        shots=[_shot()],
        canvas_width=width,
        canvas_height=height,
        fps=30,
    )
    assert out[0] is not None
    assert out[0].name == "bottom-left"


# ---------------------------------------------------------------------------
# All occupied → least-busy of the three, no fourth box
# ---------------------------------------------------------------------------


def test_all_three_occupied_picks_least_busy(tmp_path: Path):
    width, height = 720, 1280
    image = Image.new("RGB", (width, height), color=(128, 128, 128))
    draw = ImageDraw.Draw(image)
    # upper-centre: striped (busy)
    uy0, uy1 = round(0.22 * height), round(0.38 * height)
    for y in range(uy0, uy1, 2):
        draw.line((0, y, width, y), fill=(255, 255, 255))
    # bottom-left: striped (busy); bottom-centre right stays flat mid (calmer).
    y0, y1 = round(0.72 * height), round(0.88 * height)
    x1 = round(0.7 * width)
    for y in range(y0, y1, 2):
        draw.line((0, y, x1, y), fill=(255, 255, 255))

    plate = tmp_path / "all_occ.png"
    image.save(plate, format="PNG")

    bottom_band = stamp_band(width, height, text="wide phrase here", text_register="en")
    assert bottom_band is not None
    bottom_cover = replace(
        bottom_band,
        top=round(0.70 * height),
        height=round(0.20 * height),
        left=0,
        width=width,
    )
    overlays = [
        _stamp_overlay(top_fraction=0.18, end_frame=90),
        OverlayCue(
            device="stamp",
            text="bottom",
            text_register="en",
            offset_s=0.0,
            start_frame=0,
            end_frame=90,
            shot_id="sh_01",
            band=bottom_cover,
        ),
    ]
    scaled = [
        scale_candidate(c, canvas_width=width, canvas_height=height) for c in CANDIDATE_BOXES
    ]
    occupied: set[str] = set()
    for ov in overlays:
        assert ov.band is not None
        bb = ov.band.box_on(width, height)
        assert bb is not None
        for c in scaled:
            if boxes_overlap(c.box, bb):
                occupied.add(c.name)
    assert occupied == {"bottom-centre", "bottom-left", "upper-centre"}

    out = apply_caption_placements(
        [_cue()],
        {"sh_01": plate},
        overlays,
        shots=[_shot()],
        canvas_width=width,
        canvas_height=height,
        fps=30,
    )
    assert out[0] is not None
    assert out[0].name in {c.name for c in CANDIDATE_BOXES}
    # Least-busy of the three: bottom-centre (flat mid on the right dominates).
    assert out[0].name == "bottom-centre"


# ---------------------------------------------------------------------------
# Missing plate → bottom-centre
# ---------------------------------------------------------------------------


def test_missing_plate_falls_back_to_bottom_centre():
    out = apply_caption_placements(
        [_cue()],
        {},
        [],
        shots=[_shot()],
        canvas_width=720,
        canvas_height=1280,
        fps=30,
    )
    assert out[0] is not None
    assert out[0].name == "bottom-centre"
    assert out[0].an == 2


def test_unreadable_plate_falls_back_to_bottom_centre(tmp_path: Path):
    junk = tmp_path / "not_an_image.bin"
    junk.write_bytes(b"not-a-png")
    out = apply_caption_placements(
        [_cue()],
        {"sh_01": junk},
        [],
        shots=[_shot()],
        canvas_width=720,
        canvas_height=1280,
        fps=30,
    )
    assert out[0] is not None
    assert out[0].name == "bottom-centre"


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_placement_is_deterministic(tmp_path: Path):
    plate = _uniform_plate(tmp_path, (90, 90, 90))
    kwargs = dict(
        cues=[_cue(0.2, 1.0), _cue(1.0, 2.0)],
        shot_images={"sh_01": plate},
        overlay_cues=[_stamp_overlay()],
        shots=[_shot()],
        canvas_width=720,
        canvas_height=1280,
        fps=30,
    )
    a = apply_caption_placements(**kwargs)
    b = apply_caption_placements(**kwargs)
    assert a == b
    assert all(p is not None for p in a)


# ---------------------------------------------------------------------------
# serialize_ass
# ---------------------------------------------------------------------------


def test_serialize_ass_with_placement_emits_an_and_margins():
    cue = CaptionCue(start_s=1.0, end_s=2.0, text="hello")
    placement = CaptionPlacement(
        name="upper-centre",
        an=8,
        margin_l=20,
        margin_r=20,
        margin_v=300,
        box=(0, 282, 720, 486),
    )
    style = CaptionStyle(resolution=(720, 1280), font_family="Noto Sans Devanagari")
    dialogue = [
        line
        for line in serialize_ass([cue], style, placements=[placement]).splitlines()
        if line.startswith("Dialogue:")
    ]
    assert len(dialogue) == 1
    assert dialogue[0] == (
        "Dialogue: 0,0:00:01.00,0:00:02.00,Caption,,20,20,300,,{\\an8}hello"
    )


def test_serialize_ass_word_walk_shares_placement():
    cue = CaptionCue(
        start_s=1.0,
        end_s=2.0,
        text="one two",
        words=(
            CaptionWord(text="one", start_s=1.0, end_s=1.4),
            CaptionWord(text="two", start_s=1.4, end_s=2.0),
        ),
    )
    placement = CaptionPlacement(
        name="bottom-left",
        an=1,
        margin_l=60,
        margin_r=20,
        margin_v=205,
        box=(0, 922, 504, 1126),
    )
    style = CaptionStyle(resolution=(720, 1280), font_family="Noto Sans Devanagari")
    dialogue = [
        line
        for line in serialize_ass([cue], style, placements=[placement]).splitlines()
        if line.startswith("Dialogue:")
    ]
    assert len(dialogue) == 2
    assert all(",,60,20,205,,{\\an1}" in line for line in dialogue)
    assert all(line.startswith("Dialogue: 0,") for line in dialogue)


def test_serialize_ass_without_placements_stays_byte_identical():
    cue = CaptionCue(start_s=7.059, end_s=10.5, text="hello world")
    style = CaptionStyle(resolution=(1080, 1920), font_family="Noto Sans Devanagari")
    assert serialize_ass([cue], style) == serialize_ass([cue], style, placements=None)
    dialogue = [
        line
        for line in serialize_ass([cue], style).splitlines()
        if line.startswith("Dialogue:")
    ]
    assert dialogue == ["Dialogue: 0,0:00:07.06,0:00:10.50,Caption,,0,0,0,,hello world"]


def test_captions_module_has_no_pil_or_path_read():
    """K17: plate I/O stays out of captions.py (font hashing may read_bytes)."""
    import app.renderer.captions as captions_mod

    source = inspect.getsource(captions_mod)
    assert "PIL" not in source
    assert "Path.read" not in source
    assert "Image.open" not in source
    assert "ImageStat" not in source


# ---------------------------------------------------------------------------
# Fingerprint hash payload
# ---------------------------------------------------------------------------


def test_candidate_box_fraction_change_misses_placement_hash():
    placement = scale_candidate(
        CANDIDATE_BOXES[0], canvas_width=720, canvas_height=1280
    )
    base = caption_placement_content_hash([placement])
    tweaked = CandidateBox(
        name=CANDIDATE_BOXES[0].name,
        an=CANDIDATE_BOXES[0].an,
        margin_l_frac=CANDIDATE_BOXES[0].margin_l_frac,
        margin_r_frac=CANDIDATE_BOXES[0].margin_r_frac,
        margin_v_frac=CANDIDATE_BOXES[0].margin_v_frac,
        box_frac=(0.0, 0.71, 1.0, 0.88),  # retuned y0
    )
    other_candidates = (tweaked, CANDIDATE_BOXES[1], CANDIDATE_BOXES[2])
    # Same chosen name/margins/box — only the candidate TABLE changed.
    assert (
        caption_placement_content_hash([placement], candidates=other_candidates) != base
    )


def test_caption_placement_hash_none_when_placements_none():
    assert caption_placement_content_hash(None) is None


def test_scaled_demo_margins_match_reference_canvas():
    """Pin the demo's absolute margins on 720×1280."""
    bc = scale_candidate(CANDIDATE_BOXES[0], canvas_width=720, canvas_height=1280)
    bl = scale_candidate(CANDIDATE_BOXES[1], canvas_width=720, canvas_height=1280)
    uc = scale_candidate(CANDIDATE_BOXES[2], canvas_width=720, canvas_height=1280)
    assert (bc.an, bc.margin_l, bc.margin_r, bc.margin_v) == (2, 20, 20, 205)
    assert (bl.an, bl.margin_l, bl.margin_r, bl.margin_v) == (1, 60, 20, 205)
    assert (uc.an, uc.margin_l, uc.margin_r, uc.margin_v) == (8, 20, 20, 300)
    assert bc.box == (0, round(0.72 * 1280), 720, round(0.88 * 1280))
    assert bl.box == (0, round(0.72 * 1280), round(0.7 * 720), round(0.88 * 1280))
    assert uc.box == (0, round(0.22 * 1280), 720, round(0.38 * 1280))


# ---------------------------------------------------------------------------
# The clock question (K17 review finding 1): overlay start_frame/fps vs
# caption start_s. Every other test in this file uses hard cuts only, so
# transition overlap is exactly zero and the question cannot be seen.
# ---------------------------------------------------------------------------


def _dissolve_pair() -> list[Shot]:
    """Two shots joined by a 0.4s dissolve, durations as `narration_fit`
    reconciles them: shot A speaks for 3.0s, shot B for 2.0s, and B's
    `duration_s` carries the +0.4 compensation D5 subtracts back off.

    So on the FINISHED video: total 5.0s (== 3.0 + 2.0 of narration),
    B's footage starts at 2.6s, and B's first spoken character is at
    3.0s. Onsets differ by the overlap; lengths do not.
    """
    a = _shot("sh_01", duration_s=3.0)
    b = _shot("sh_02", duration_s=2.4)
    return [
        a.model_copy(
            update={"transition_out": Transition(type=TransitionType.DISSOLVE, duration_s=0.4)}
        ),
        b.model_copy(update={"order": 1}),
    ]


def _top_calm_bottom_busy(tmp_path: Path, name: str) -> Path:
    """Flat above the midline, checkerboard below → upper-centre is the
    calmest box, so a placement of `upper-centre` proves this plate was
    the one measured."""
    plate = Image.new("RGB", (720, 1280), color=(128, 128, 128))
    plate.paste(_checkerboard((720, 640), (0, 0, 0), (255, 255, 255)), (0, 640))
    path = tmp_path / name
    plate.save(path, format="PNG")
    return path


def test_dissolve_shifts_shot_onset_but_not_timeline_length():
    shots = _dissolve_pair()
    starts = compute_shot_start_times(shots)
    assert starts["sh_01"] == 0.0
    # Head of the crossfade, i.e. 0.4s BEFORE sh_02's first spoken word.
    assert starts["sh_02"] == pytest.approx(2.6)
    # ...yet the rendered length still equals the narration's own total,
    # which is what makes ASS timestamps usable as video timestamps.
    assert compute_timeline_duration(shots) == pytest.approx(3.0 + 2.0)


def test_cue_on_a_post_dissolve_shot_reads_that_shot_s_plate(tmp_path: Path):
    """`_shot_id_for_cue`'s window is [onset - overlap, offset), which
    CONTAINS [onset, offset) — so a cue at 3.0s belongs to sh_02 even
    though sh_02's video window opened at 2.6s."""
    flat = _uniform_plate(tmp_path)
    busy_bottom = _top_calm_bottom_busy(tmp_path, "sh_02.png")
    out = apply_caption_placements(
        [_cue(3.0, 4.0)],
        {"sh_01": flat, "sh_02": busy_bottom},
        [],
        shots=_dissolve_pair(),
        canvas_width=720,
        canvas_height=1280,
        fps=30,
    )
    assert out[0] is not None
    assert out[0].name == "upper-centre"


def test_overlay_live_uses_finished_video_time_across_a_dissolve(tmp_path: Path):
    """The finding-1 pin. Both operands of `_overlay_live` are moments in
    the finished video, so an overlay that lives only inside the 0.4s
    crossfade never occupies a caption that starts after it.

    If either side were shifted by the overlap to "convert clocks", the
    first case below would flip to bottom-centre: an overlay window of
    [2.6, 2.9) becomes [3.0, 3.3), which does overlap the caption. It is
    the overlap value 0.4 that makes this test able to tell.
    """
    plate = _top_calm_bottom_busy(tmp_path, "sh_02.png")
    shots = _dissolve_pair()
    images = {"sh_01": plate, "sh_02": plate}
    cue = _cue(3.0, 4.0)

    # Frames 78..87 == video time [2.6, 2.9): entirely inside the
    # crossfade, gone before the caption is painted at 3.0s.
    during_crossfade = _stamp_overlay(start_frame=78, end_frame=87, top_fraction=0.18)
    out = apply_caption_placements(
        [cue], images, [during_crossfade], shots=shots,
        canvas_width=720, canvas_height=1280, fps=30,
    )
    assert out[0] is not None
    assert out[0].name == "upper-centre"

    # Frames 78..104 == [2.6, 3.4667): still on screen at 3.0s, so the
    # stamp band really does knock upper-centre out.
    across_the_caption = _stamp_overlay(start_frame=78, end_frame=104, top_fraction=0.18)
    out = apply_caption_placements(
        [cue], images, [across_the_caption], shots=shots,
        canvas_width=720, canvas_height=1280, fps=30,
    )
    assert out[0] is not None
    assert out[0].name == "bottom-centre"
