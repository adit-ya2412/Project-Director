"""Run the caption-romanization pass over an ALREADY-NARRATED project.

    python scripts/backfill_caption_romanization.py <project_id>            # preview
    python scripts/backfill_caption_romanization.py <project_id> --apply    # write

caption_romanization.md §3.6 (and RV-R9 in §8.10): the backfill function
lives in `app/workflow/steps/romanize_captions.py` but had no caller —
no route, no script, no test — so it was reachable only from an ad-hoc
REPL. This is that entry point.

## Why a backfill exists at all

`RomanizeCaptionsStep` deliberately skips any project with
`metadata.narration_locked` (see its module docstring). Appending a
`produced_by=CAPTION_ROMANIZATION` version to a narrated project would
reset `status` to DRAFT and make `render.py::_resolve_narration_rows`
return None — a SILENT video, with no error anywhere.
`backfill_caption_romanization` is the path that does it safely: it
re-stamps `produced_by=NARRATION` and re-approves if the version it
romanized from was approved.

## Preview is the default, deliberately

This mutates a finished project. Preview runs the real planner (so you
see the real model output and the real cost) but appends NO version and
commits NOTHING — the session is rolled back. Read the output, then
re-run with `--apply`.

Preview still costs money: it makes the same LLM calls. It is cheap
(~0.06 ¢ for a 7-scene project on the cheap model) and it is the only
way to see the romanization before it is stored.

## After --apply

The re-render triggers on its own — do NOT force it (RV-R1, §8.2).
Appending a version carries every shot binding forward with a fresh
`updated_at`, so `RenderStep.is_satisfied` correctly sees the existing
video as stale.
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
import uuid
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))

from app.core.config import settings  # noqa: E402
from app.db.session import async_session_factory  # noqa: E402
from app.planners.caption_romanizer.planner import (  # noqa: E402
    CaptionRomanizer,
    needs_romanization,
)
from app.providers.openai_provider import OpenAIPlanningProvider  # noqa: E402
from app.repositories.llm_call_repository import LlmCallRepository  # noqa: E402
from app.repositories.project_repository import PostgresProjectRepository  # noqa: E402
from app.schemas.timeline import TimelineStatus  # noqa: E402
from app.timeline.service import TimelineService  # noqa: E402
from app.workflow.context import RunContext  # noqa: E402
from app.workflow.steps.romanize_captions import (  # noqa: E402
    backfill_caption_romanization,
)

_DEVANAGARI = re.compile(r"[ऀ-ॿ]")


def _report(narration: str, caption: str | None, groups: list[int] | None) -> list[str]:
    """The same invariants the planner's validator enforces, re-checked
    here so the operator sees them rather than trusting the run.

    §10.3: with grouping, the caption legitimately has FEWER words than
    the narration - a merged numeral (`उन्नीस सौ इकतीस` -> `1931`)
    consumes three narration words and displays one. So the count to
    check is `sum(groups)`, not the caption's own word count. Comparing
    word counts directly, as this did before §10, false-positives on
    every successful merge.
    """
    problems: list[str] = []
    if caption is None:
        problems.append("NOT ROMANIZED (validator could not be satisfied, or scene skipped)")
        return problems
    n_src = len(narration.split())
    n_out = len(caption.split())
    if groups is None:
        if n_src != n_out:
            problems.append(f"WORD COUNT {n_src} -> {n_out} and no groups (will fall back)")
    else:
        if sum(groups) != n_src:
            problems.append(f"GROUPS cover {sum(groups)} words, narration has {n_src}")
        if len(groups) != n_out:
            problems.append(f"GROUPS has {len(groups)} entries, caption has {n_out} words")
    if _DEVANAGARI.search(caption):
        problems.append("RESIDUAL DEVANAGARI in display text")
    return problems


async def _screen_check(ctx: RunContext, timeline, planned) -> int:
    """Run the REAL renderer path over the candidate scenes and report
    what would actually reach the screen.

    This is the check the word-level report cannot make. §10.5's straddle
    guard falls a whole scene back to `narration_text` when a merged
    group is split across a cue boundary — so a scene can pass every
    validator and STILL render in Devanagari. That would be a regression
    against today's output, where the scene is at least romanized. Find
    it here, before `--apply`, not in a render.
    """
    from sqlalchemy import select

    from app.models.narration import NarrationModel
    from app.renderer.captions import derive_caption_cues

    # Same resolution NarrationStep uses: `metadata.voice_id` is often
    # None on projects that never had a voice chosen explicitly, and the
    # step falls back to the configured default. Filtering on a None
    # voice matches nothing and silently skips this whole check.
    voice_id = timeline.metadata.voice_id or settings.elevenlabs_voice_id
    rows = (
        (
            await ctx.session.execute(
                select(NarrationModel).where(
                    NarrationModel.project_id == uuid.UUID(ctx.project_id),
                    NarrationModel.voice_id == voice_id,
                )
            )
        )
        .scalars()
        .all()
    )
    by_scene = {r.scene_id: r for r in rows}
    if not all(s.id in by_scene for s in timeline.scenes):
        print("\n(no narration rows for the active voice - skipping the on-screen check)")
        return 0

    candidate = timeline.model_copy(update={"scenes": planned})
    ordered = [by_scene[s.id] for s in timeline.scenes]
    cues = derive_caption_cues(candidate, ordered)

    # A scene that fell back renders its narration verbatim, so its
    # Devanagari shows up directly in the cue text.
    devanagari_cues = [c for c in cues if _DEVANAGARI.search(c.text)]
    digit_words = sorted(
        {w.text for c in cues for w in c.words if any(ch.isdigit() for ch in w.text)}
    )

    print("\n=== what would reach the screen ===")
    print(f"  cues                     : {len(cues)}")
    print(f"  cues with Devanagari     : {len(devanagari_cues)}  (must be 0)")
    print(f"  numerals displayed       : {digit_words}")
    if devanagari_cues:
        print("  !! AT LEAST ONE SCENE FELL BACK TO MIXED SCRIPT - do NOT apply.")
        print("     Most likely §10.5's straddle guard. Sample:")
        for c in devanagari_cues[:3]:
            print(f"       {c.text}")
        return 1
    return 0


async def _preview(ctx: RunContext) -> int:
    timeline = await ctx.timeline_service.get_active(ctx.project_id)
    if timeline is None:
        print("no active timeline")
        return 1

    provider = OpenAIPlanningProvider(model=settings.openai_planning_model_cheap)
    planner = CaptionRomanizer(provider, LlmCallRepository(ctx.session))
    planned = await planner.plan(project_id=ctx.project_id, scenes=timeline.scenes)

    failures = 0
    for scene in planned:
        print(f"\n--- {scene.id} ---")
        print(f"  narration : {scene.narration_text}")
        print(f"  caption   : {scene.caption_text}")
        groups = scene.caption_word_groups
        if groups and any(g > 1 for g in groups):
            merged = []
            src_words, i = scene.narration_text.split(), 0
            for token, covers in zip((scene.caption_text or "").split(), groups, strict=False):
                if covers > 1:
                    merged.append(f"{' '.join(src_words[i : i + covers])!r} -> {token!r}")
                i += covers
            print(f"  merges    : {'; '.join(merged)}")
        for problem in _report(scene.narration_text, scene.caption_text, groups):
            failures += 1
            print(f"  !! {problem}")

    romanized = sum(1 for s in planned if s.caption_text)
    print(f"\n{romanized}/{len(planned)} scenes romanized, {failures} problem(s)")
    failures += await _screen_check(ctx, timeline, planned)
    print("\nPREVIEW ONLY - nothing was written. Re-run with --apply to store it.")
    return 1 if failures else 0


async def _apply(ctx: RunContext) -> int:
    before = await ctx.timeline_service.get_active(ctx.project_id)
    if before is None:
        print("no active timeline")
        return 1
    was_approved = before.status == TimelineStatus.APPROVED
    pending = sum(1 for s in before.scenes if needs_romanization(s))
    print(f"active v{before.version} produced_by={before.produced_by} status={before.status}")
    print(f"{pending}/{len(before.scenes)} scene(s) need romanization")

    result = await backfill_caption_romanization(ctx)
    if result.outcome != "ok":
        print(f"FAILED: {result.error}")
        await ctx.session.rollback()
        return 1
    await ctx.session.commit()

    after = await ctx.timeline_service.get_active(ctx.project_id)
    assert after is not None
    print(f"\nwrote v{after.version} produced_by={after.produced_by} status={after.status}")
    print(f"  caption_romanization_attempted = {after.metadata.caption_romanization_attempted}")
    print(f"  scenes with caption_text       = {sum(1 for s in after.scenes if s.caption_text)}")

    # The two invariants that make this safe to render (see module docstring).
    if after.produced_by.value != "narration":
        print("  !! produced_by is NOT narration - render would ship SILENT")
    if was_approved and after.status != TimelineStatus.APPROVED:
        print("  !! version was approved before and is not now - approval gate reopened")
    return 0


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_id")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="actually write the version (default is a rollback-only preview)",
    )
    args = parser.parse_args()

    async with async_session_factory() as session:
        ctx = RunContext(
            project_id=args.project_id,
            session=session,
            repo=PostgresProjectRepository(session),
            timeline_service=TimelineService(session),
        )
        if args.apply:
            return await _apply(ctx)
        try:
            return await _preview(ctx)
        finally:
            # Preview must leave nothing behind - not even the llm_call
            # rows the planner inserts along the way.
            await session.rollback()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # Devanagari on a cp1252 console
    raise SystemExit(asyncio.run(main()))
