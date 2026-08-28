"""Edit a scene's `narration_text` in place and re-align its shot spans.

    python scripts/edit_narration_text.py <project_id> \
        --scene sc_03 --find 2026 --replace "दो हजार छब्बीस"          # preview
    python scripts/edit_narration_text.py <project_id> ... --apply     # write

## Why this exists

ElevenLabs reads a 4-digit year in a Hindi sentence digit-by-digit —
`2026` comes out as gibberish — but reads the spelled-out form correctly.
The fix is to change what the TTS is *given*, not what the viewer reads:
spell the number out in `narration_text`, and let the caption romanizer
merge it back to digits on screen (caption_romanization.md §10). That
round trip only works if the spelled-out form is in the narration, so
this script is step one of it.

## The part that is easy to get wrong

`Shot.narration_span` is a pair of CHARACTER OFFSETS into
`scene.narration_text`, and the spans of a scene's shots tile it
losslessly. Changing the text by hand without shifting every span after
the edit point silently desynchronises captions from audio for the rest
of the scene — no error, just wrong words on screen. This script does
the shift and then asserts the tiling still holds.

It also clears `caption_text` / `caption_word_groups` on the edited
scene, because the stored display text now describes words that are no
longer there. `needs_romanization` treats a missing group list as "needs
the pass", so a later `backfill_caption_romanization` run picks up
exactly the edited scenes and leaves the rest alone.

## Order of operations

1. This script (`--apply`). It appends a `produced_by=HUMAN` version.
2. Re-run narration. `NarrationStep.is_satisfied` is just
   `produced_by == NARRATION`, so a HUMAN version re-triggers it, and
   the content-hash cache means only the scenes whose text actually
   changed are re-synthesised and re-paid for.
3. `scripts/backfill_caption_romanization.py` to romanize the cleared
   scenes.
4. Re-render.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))

from app.db.session import async_session_factory  # noqa: E402
from app.schemas.timeline import ProducedBy, Timeline  # noqa: E402
from app.timeline.service import TimelineService  # noqa: E402


def _shift_spans(
    shots, pos: int, old_len: int, delta: int
) -> list[tuple[str, tuple[int, int], tuple[int, int]]]:
    """Return (shot_id, old_span, new_span) for every shot with a span.

    A shot ending at or before the edit is untouched. A shot starting at
    or after the edited region moves wholesale. The one shot containing
    the edit keeps its start and grows (or shrinks) by `delta`.
    """
    end_of_old = pos + old_len
    moves = []
    for shot in shots:
        if shot.narration_span is None:
            continue
        start, end = shot.narration_span
        if end <= pos:
            new = (start, end)
        elif start >= end_of_old:
            new = (start + delta, end + delta)
        else:
            new = (start, end + delta)
        moves.append((shot.id, (start, end), new))
    return moves


def _check_tiling(scene_id: str, text_len: int, spans: list[tuple[int, int]]) -> list[str]:
    """Spans must still tile [0, len(text)) with no gap or overlap."""
    problems = []
    ordered = sorted(spans)
    if ordered and ordered[0][0] != 0:
        problems.append(f"{scene_id}: first span starts at {ordered[0][0]}, expected 0")
    for (_, prev_end), (next_start, _) in zip(ordered, ordered[1:], strict=False):
        if prev_end != next_start:
            problems.append(f"{scene_id}: gap/overlap between {prev_end} and {next_start}")
    if ordered and ordered[-1][1] != text_len:
        problems.append(f"{scene_id}: last span ends at {ordered[-1][1]}, text is {text_len}")
    return problems


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("project_id")
    ap.add_argument("--scene", action="append", required=True, help="scene id (repeatable)")
    ap.add_argument("--find", required=True)
    ap.add_argument("--replace", required=True)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    delta = len(args.replace) - len(args.find)
    targets = set(args.scene)

    async with async_session_factory() as session:
        svc = TimelineService(session)
        timeline = await svc.get_active(args.project_id)
        if timeline is None:
            print("no active timeline")
            return 1
        print(f"active v{timeline.version} produced_by={timeline.produced_by}")
        print(f"replacing {args.find!r} -> {args.replace!r}  (delta {delta:+d} chars)\n")

        problems: list[str] = []
        planned: dict[str, tuple[str, list]] = {}

        for scene in timeline.scenes:
            if scene.id not in targets:
                continue
            pos = scene.narration_text.find(args.find)
            if pos < 0:
                problems.append(f"{scene.id}: {args.find!r} not found")
                continue
            if scene.narration_text.count(args.find) > 1:
                problems.append(
                    f"{scene.id}: {args.find!r} appears "
                    f"{scene.narration_text.count(args.find)} times - refusing to guess"
                )
                continue
            new_text = scene.narration_text.replace(args.find, args.replace, 1)
            moves = _shift_spans(scene.shots, pos, len(args.find), delta)
            problems += _check_tiling(scene.id, len(new_text), [m[2] for m in moves])

            print(f"--- {scene.id} ---")
            print(
                f"  before: ...{scene.narration_text[max(0, pos - 40) : pos + len(args.find) + 40]}..."
            )
            print(f"  after : ...{new_text[max(0, pos - 40) : pos + len(args.replace) + 40]}...")
            for shot_id, old, new in moves:
                if old != new:
                    print(f"    {shot_id}: {old} -> {new}")
            if scene.caption_text:
                print("    clearing stale caption_text / caption_word_groups")
            planned[scene.id] = (new_text, moves)

        missing = targets - {s.id for s in timeline.scenes}
        problems += [f"scene {s} not in this timeline" for s in sorted(missing)]

        if problems:
            print("\nPROBLEMS:")
            for p in problems:
                print(f"  !! {p}")
            return 1
        if not planned:
            print("nothing to do")
            return 1

        if not args.apply:
            print("\nPREVIEW ONLY - nothing written. Re-run with --apply.")
            return 0

        def _edit(base: Timeline) -> Timeline:
            for scene in base.scenes:
                if scene.id not in planned:
                    continue
                new_text, moves = planned[scene.id]
                scene.narration_text = new_text
                new_spans = {shot_id: new for shot_id, _old, new in moves}
                for shot in scene.shots:
                    if shot.id in new_spans:
                        shot.narration_span = new_spans[shot.id]
                # Stale: it describes words that are no longer there.
                scene.caption_text = None
                scene.caption_word_groups = None
            return base

        new_timeline = await svc.append_version(
            args.project_id,
            produced_by=ProducedBy.HUMAN,
            transform=_edit,
            owns=frozenset({"scenes"}),
        )
        await session.commit()
        print(f"\nwrote v{new_timeline.version} produced_by={new_timeline.produced_by} ")
        print("NarrationStep will re-run (produced_by is no longer NARRATION);")
        print("only the edited scenes are re-synthesised - the rest hit the cache.")
        return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(asyncio.run(main()))
