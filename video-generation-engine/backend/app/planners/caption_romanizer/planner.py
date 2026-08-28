"""Caption romanizer (caption_romanization.md §3.3, §11).

A per-scene LLM pass that writes `Scene.caption_text` (a single-script
Latin rendering of `narration_text` for captions only) and
`Scene.caption_word_groups` (§10.3: how many consecutive narration words
each display token replaces — > 1 only for a Hindi number-word group
collapsed into one digit token, e.g. `उन्नीस सौ इकतीस` -> `1931`).
Narration text, TTS, and `Shot.narration_span` offsets are never
touched.

§11 split this pass in two: the LLM does plain 1:1 transliteration only
(no merging, no `covers` decisions — see `schemas.py` and
`prompts/caption_romanizer/v1.md`), and `numerals.py`'s deterministic
pass runs AFTER validation to find and merge Hindi number-word runs into
digit tokens. The LLM cannot over-merge (it no longer decides merging at
all) and cannot produce a silently wrong numeral (the value is computed,
never guessed) — both were live defects under §10's LLM-side merging.

Failure is per-scene and never fatal: if the validator cannot be
satisfied after the shared repair loop, that scene's `caption_text`
(and `caption_word_groups`) stay None and captions fall back to mixed
script. Transient provider errors still propagate so the workflow step
can retry.
"""

from __future__ import annotations

import asyncio
import re
import uuid

from app.core.errors import TransientError
from app.core.logging import get_logger
from app.planners.caption_romanizer.numerals import apply_numeral_merging
from app.planners.caption_romanizer.schemas import CaptionRomanizerOutput
from app.planners.repair import run_structured_with_repair
from app.prompts.loader import load_prompt
from app.providers.base import PlanningLLMProvider
from app.repositories.llm_call_repository import LlmCallRepository
from app.schemas.timeline import Scene
from app.utils.bounded_gather import bounded_gather, planner_concurrency

logger = get_logger(__name__)

AGENT = "caption_romanizer"
PROMPT_VERSION = "v1"

# Devanagari block (U+0900–U+097F), including danda `।`. Residual
# characters in this range in the output are a validation failure.
_DEVANAGARI_RE = re.compile(r"[ऀ-ॿ]")


def contains_devanagari(text: str) -> bool:
    return _DEVANAGARI_RE.search(text) is not None


def needs_romanization(scene: Scene) -> bool:
    """True when this scene has mixed-script narration and no usable
    display text. Latin-only scenes skip the LLM.

    A scene romanized BEFORE §10 has `caption_text` but no
    `caption_word_groups`, because grouping did not exist yet. It still
    needs the pass: without groups it can never merge a spelled-out
    Hindi numeral into digits, so it would keep showing
    `unnis sau ikatees` next to a `1990: Osho Dies` text card. Treat a
    missing group list as "not yet romanized under the current
    contract" rather than as "already done".

    A scene romanized under §10/§11 with nothing to merge stores
    `[1, 1, 1, ...]` - a real list, not None - so it is correctly left
    alone.
    """
    if scene.caption_text is not None and scene.caption_word_groups is not None:
        return False
    return contains_devanagari(scene.narration_text)


def is_latin_word(word: str) -> bool:
    """A token with no Devanagari — English loanwords, digits, already-
    Latin Hinglish — must be copied exactly. Matches the plan's
    `is_latin` check."""
    return not contains_devanagari(word)


def romanization_violations(src: str, out: CaptionRomanizerOutput) -> list[str]:
    """The §2.2 invariants, in code. Never trust the prompt alone.

    1. Same word count as the narration — plain 1:1, no merging, no
       dropping, no adding.
    2. A Latin source word is copied exactly, unchanged.
    3. No residual Devanagari (including a leftover danda) anywhere in
       the output.

    §10.3's invariants 4-5 (about a merged group's contents) are
    withdrawn by §11 — the LLM no longer merges anything, so there is no
    merged group here to check. Numeral merging happens afterwards, as a
    separate deterministic pass (`numerals.py`) over output that has
    already passed this validator.
    """
    violations: list[str] = []
    src_words = src.split()
    out_words = out.caption_text.split()

    if len(out_words) != len(src_words):
        violations.append(f"word count changed: {len(src_words)} -> {len(out_words)}")

    for i, (a, b) in enumerate(zip(src_words, out_words, strict=False)):
        if is_latin_word(a) and a != b:
            violations.append(f"word {i}: Latin word {a!r} was altered to {b!r}")

    if contains_devanagari(out.caption_text):
        violations.append("output still contains Devanagari")
    return violations


def _make_validator(scene: Scene):
    src = scene.narration_text

    def _validate(output: CaptionRomanizerOutput) -> list[str]:
        return romanization_violations(src, output)

    return _validate


def _build_user_content(scene: Scene) -> str:
    return (
        "Romanize this scene's narration into Hinglish (Latin script). "
        "Same number of words, same order — one Latin word per narration "
        "word, nothing merged, nothing dropped, nothing added. Script "
        "change only — do not translate.\n\n"
        f"Narration:\n{scene.narration_text}"
    )


class CaptionRomanizer:
    name = AGENT

    def __init__(self, provider: PlanningLLMProvider, llm_call_repo: LlmCallRepository) -> None:
        self._provider = provider
        self._llm_call_repo = llm_call_repo

    async def plan(self, *, project_id: str, scenes: list[Scene]) -> list[Scene]:
        """Return scenes with `caption_text` filled where the pass
        succeeded. Scenes that needed no work, or whose repair loop
        failed, come back with `caption_text` still None. Never raises
        `PermanentError` — a captions cosmetic miss must not destroy
        the run (caption_romanization.md §3.5). `TransientError` still
        propagates so the step can retry a rate-limit."""
        system_prompt = load_prompt(AGENT, PROMPT_VERSION)
        db_lock = asyncio.Lock()

        async def _one_scene(scene: Scene) -> Scene:
            if not needs_romanization(scene):
                return scene
            try:
                output = await run_structured_with_repair(
                    provider=self._provider,
                    llm_call_repo=self._llm_call_repo,
                    project_id=uuid.UUID(project_id),
                    agent=AGENT,
                    prompt_version=PROMPT_VERSION,
                    system_prompt=system_prompt,
                    user_content=_build_user_content(scene),
                    response_model=CaptionRomanizerOutput,
                    validate=_make_validator(scene),
                    db_lock=db_lock,
                )
            except TransientError:
                raise
            except Exception as exc:
                logger.warning(
                    "caption_romanizer.scene_failed",
                    extra={
                        "project_id": project_id,
                        "scene_id": scene.id,
                        "error": str(exc),
                    },
                )
                return scene
            # The LLM output is already validated 1:1 against
            # `narration_text` (same word count, order preserved). The
            # numeral pass is deterministic and code-only (§11): it can
            # only ever merge a run that satisfies all of §11.5's rules,
            # never guess, never introduce a wrong value.
            narration_words = scene.narration_text.split()
            display_words = output.caption_text.split()
            caption_text, caption_word_groups = apply_numeral_merging(
                narration_words, display_words
            )
            return scene.model_copy(
                update={
                    "caption_text": caption_text,
                    "caption_word_groups": caption_word_groups,
                }
            )

        gathered = await bounded_gather(scenes, _one_scene, concurrency=planner_concurrency())
        planned: list[Scene] = []
        for i, item in enumerate(gathered):
            if isinstance(item, TransientError):
                raise item
            if isinstance(item, Exception):
                logger.warning(
                    "caption_romanizer.scene_failed",
                    extra={
                        "project_id": project_id,
                        "scene_id": scenes[i].id,
                        "error": str(item),
                    },
                )
                planned.append(scenes[i])
                continue
            planned.append(item)
        return planned
