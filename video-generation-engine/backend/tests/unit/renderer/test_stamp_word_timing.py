"""K14 review finding 3: no stamp word may be scheduled past its hold.

`STAMP_HOLD_S` lives in Python (`app/renderer/compositor.py`, spike-
pinned at 0.86s) and the word-entry delays live in TypeScript
(`compositor/src/stampWordTiming.ts`). Nothing guarded that pair, so the
fixed 0/4/14/24 table plus +10 per further word put a 5th word at frame
34 and a 6th at 44 inside a ~26-frame hold: words that never rendered,
with no error and no dropped cue.

These tests read BOTH sides. The schedule is executed as the real
TypeScript module (node's type stripping), not re-implemented here — a
second copy of the arithmetic is exactly the drift being guarded
against.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from app.renderer.compositor import STAMP_HOLD_S

FPS = 30
TIMING_TS = (
    Path(__file__).resolve().parents[4] / "compositor" / "src" / "stampWordTiming.ts"
)
NODE = shutil.which("node")


def _schedule(word_counts: list[int], window_frames: int) -> dict:
    """Run the real TS module and return its schedule + constants."""
    script = (
        f'const m = await import({TIMING_TS.as_uri()!r});'
        "const out = {"
        "exit: m.EXIT_FRAMES, entry: m.MIN_WORD_ENTRY_FRAMES,"
        "nominal: m.WORD_DELAYS_FRAMES, schedules: {}};"
        f"for (const n of {json.dumps(word_counts)}) "
        f"out.schedules[n] = m.wordDelaySchedule(n, {window_frames});"
        "console.log(JSON.stringify(out));"
    ).replace("'", '"')
    proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [NODE, "--experimental-strip-types", "--input-type=module", "-e", script],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(proc.stdout.strip().splitlines()[-1])


pytestmark = pytest.mark.skipif(
    NODE is None or not TIMING_TS.exists(),
    reason="needs node (>=22.6, for --experimental-strip-types) and the compositor sources",
)


def test_stamp_words_are_all_scheduled_inside_the_hold():
    """Every word of a 1-6 word stamp lands inside the pinned hold with
    room to finish its entry before the 3-frame exit snap."""
    window = round(STAMP_HOLD_S * FPS)
    assert window == 26
    result = _schedule([1, 2, 3, 4, 5, 6], window)
    latest_usable = window - result["exit"] - result["entry"]
    for count in range(1, 7):
        delays = result["schedules"][str(count)]
        assert len(delays) == count
        assert delays == sorted(delays)
        assert max(delays) <= latest_usable, f"{count} words: {delays} in {window} frames"
        assert max(delays) < window


def test_the_spike_rhythm_survives_for_a_three_word_phrase():
    """0 / 4 / 14 is the look being reproduced (EVERY / 3rd / SUV). It
    fits the hold, so it must come through untouched."""
    result = _schedule([2, 3], round(STAMP_HOLD_S * FPS))
    assert result["nominal"][:3] == [0, 4, 14]
    assert result["schedules"]["2"] == [0, 4]
    assert result["schedules"]["3"] == [0, 4, 14]


def test_the_old_fixed_table_would_have_missed_the_hold():
    """The regression this guards: nominal delays for 5 and 6 words are
    34 and 44 frames, past a 26-frame hold — which is why the schedule
    is derived from the window instead of pinned."""
    result = _schedule([6], round(STAMP_HOLD_S * FPS))
    nominal = list(result["nominal"])
    fifth = nominal[-1] + 10
    sixth = nominal[-1] + 20
    assert (fifth, sixth) == (34, 44)
    assert fifth > round(STAMP_HOLD_S * FPS)
    assert max(result["schedules"]["6"]) < round(STAMP_HOLD_S * FPS)


def test_a_hold_clamped_short_by_the_end_of_a_shot_still_fits_every_word():
    """`collect_emphasis_overlay_cues` clamps the hold to the remaining
    shot and the remaining film, so the window can be far shorter than
    STAMP_HOLD_S. Even at 9 frames no word is scheduled past it."""
    result = _schedule([2, 4], 9)
    for count in ("2", "4"):
        delays = result["schedules"][count]
        assert max(delays) <= 9 - result["exit"] - result["entry"]
        assert delays == sorted(delays)
