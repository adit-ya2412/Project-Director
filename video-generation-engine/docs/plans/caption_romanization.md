# Caption Romanization — one script on screen, mixed script in the ear

**Status:** §1–§9 COMPLETE and live. §10 built and shipped, then found
defective in live use — **§11 supersedes its LLM-side merging and is
planned, not built.** §3.1–§3.5 implemented 2026-08-28 (P-R1),
reviewed the same day (§8, RV-R1..RV-R9 — two were corrections to
wrong claims in this document), and §3.6's backfill **executed against
`606f393e`** the same day (§9). Written 2026-08-28, from a real
viewer complaint on project `606f393e` ("OSHO the legend"): captions flip
between Devanagari and Latin **mid-sentence**, which is tiring to read,
while the on-screen text cards are already clean single-script Latin.

The fix is **not** "write the script in Latin." That trades the ear for
the eye, and this codebase deliberately chose the ear (§1.2). This plan
adds a *display* layer so captions can be romanized while narration keeps
the mixed script the TTS actually wants.

---

## 0. Navigation — read before writing code

| # | Read | Why |
|---|---|---|
| 1 | `frontend/src/pages/NewProject.tsx` — the "Line breaks become cuts" alert | States the tradeoff this plan works around, in the product's own words: *"Mixed script (Devanagari for Hindi words, Latin for English loanwords) **measurably sounds better** than fully Romanised Hindi when read aloud."* The script format is optimised for TTS. Do not "fix" it. |
| 2 | `backend/app/renderer/captions.py` — `derive_caption_cues`, `_word_spans`, `serialize_ass` | The whole consumer surface. §2.1's separability argument is verified against these three functions; re-verify before relying on it. |
| 3 | `docs/plans/style_extensions.md` §3 (Feature A) | Word-level caption highlighting. **The reason word count is a hard invariant here** (§2.2) — per-word timing comes from whitespace splitting. |
| 4 | `backend/app/planners/repair.py::run_structured_with_repair` + any planner's `_make_validator` | The exact validate-and-repair pattern §3.3 must reuse. Do not hand-roll retry logic. |
| 5 | `docs/plans/prompt_fixes.md` §2.1 | The "a prompt cannot enforce what the caller cannot see" rule. Relevant in reverse here: this pass IS per-scene, and its invariant IS per-scene, so a prompt instruction is legitimate — but it still needs a code-level validator, not trust. |

---

## 1. Origin and scope

### 1.1 What prompted this

A viewer reported that reading captions on `606f393e` was "disturbing" —
they flip script word by word:

```
एक Indian guru जिसके पास 90 Rolls-Royce थीं।
उन्नीस सौ इकतीस में उनका India में जन्म हुआ।
```

Meanwhile the same video's text cards are already uniform Latin:
`90 ROLLS-ROYCE`, `RAJNEESHPURAM, OREGON`, `1990: Osho Dies`. So the
video is internally inconsistent: cards read as English, captions
code-switch every few words.

### 1.2 Why the obvious fix is wrong

Captions are the narration text **verbatim** — that is a deliberate D2
design decision (`captions.py` module docstring: *"script text + TTS
alignment -> ASS cue file... Never transcription of our own narration
audio"*). So the caption script and the narration script are the same
string today.

And the narration script is mixed **on purpose**, per the product's own
guidance to writers (§0 item 1). Romanising the source script would
degrade narration to fix captions.

⚠ **That "measurably sounds better" claim has no citation I could find.**
It is asserted in `NewProject.tsx` guidance. This plan does not depend on
it being true — but if anyone ever wants to revisit option §4.3, that
claim is the thing to re-measure first, not assume.

### 1.3 In scope

1. A **romanized display text** stored per scene on the Timeline (§3.1).
2. A **plan-time LLM pass** that produces it, validated for word-count
   and order preservation (§3.3).
3. **Captions read the display text**; narration keeps `narration_text`
   (§3.4).
4. A **backfill path** for already-rendered projects (§3.6) — this is
   caption-only, so it needs no re-planning.

### 1.4 Explicitly OUT of scope

- **Text cards.** `Shot.text_card` is already written in Latin by the
  Shot Planner (verified on `606f393e`: six cards, all Latin). Leave
  `derive_text_card_cues` alone entirely.
- **Narration text.** `scene.narration_text` is the TTS input and the
  alignment's coordinate system. It must not change. Every character
  offset in `Shot.narration_span` indexes into it.
- **Romanising the source script** (§1.2).
- **Translation.** This is a script change only — same words, same
  meaning, same order. Anything that changes *word choice* is a bug.

⚠ **Constraint for whoever adds a script-edit endpoint** (RV-R8,
§8.9). Stale `caption_text` is unreachable today: `narration_text` is
assigned in exactly one place (`scene/planner.py:283`) and no API path
mutates it afterwards, so `_aligned_display_tokens`' word-count fallback
never has to save us. If an endpoint that edits `narration_text` is ever
added, it **must** clear `caption_text` AND reset
`metadata.caption_romanization_attempted`. A same-word-count edit
(`1931` → `1932`) leaves the count matching, skips the fallback, and
displays the *old* word on screen with nothing to catch it.

---

## 2. Lessons carried forward — the invariants this rests on

### 2.1 Caption text and caption timing are separable — VERIFIED

This is the entire reason the plan is cheap. Checked against real code,
not assumed:

- Cue timing comes from the alignment arrays:
  `start_s = scene_offset_s + char_starts[seg_start]`,
  `end_s = scene_offset_s + char_ends[seg_end - 1]`
  (`captions.py:186-187`).
- Cue *text* is an independent display string: `text=text`
  (`captions.py:188`), sliced from `narration_text`.
- Per-word timing likewise: `char_starts[first]` / `char_ends[last]`
  (`captions.py:352-353`).

**So swapping the displayed string changes nothing about timing** — as
long as the word structure lines up (§2.2). The TTS never sees the
display text; the renderer never sees the mixed script.

### 2.2 Word count and order are a HARD invariant, not a nicety

`_word_spans` splits on `text[index].isspace()` (`captions.py:359`) and
`_highlighted_dialogue_lines` emits one Dialogue line per word. Feature A
(`style_extensions.md` §3) drives per-word highlighting off that list.

**If the romanized text has a different number of words, per-word
highlight timing silently desyncs** — the wrong word lights up, and
nothing errors. That is the single most dangerous failure mode in this
plan, and it is invisible in a render.

Therefore: **validate word count and order in code, at plan time, with
the repair loop. Never trust the prompt alone.** (Measured: the LLM got
31→31, 68→68, 70→70 on three real scenes — but three passes is not a
guarantee, it is a reason to expect the validator to rarely fire.)

### 2.3 An LLM in the render path would break determinism (I5)

The romanization MUST happen at plan time and be stored on the Timeline,
exactly like every other planner output. Doing it inside
`derive_caption_cues` would:

- make each render non-deterministic (I5 violation),
- change `cue_list_content_hash` unpredictably, poisoning the render
  cache (the R2 lesson, hit repeatedly in this codebase),
- cost money per render instead of per project.

Stored-once is also what makes §3.6's backfill possible.

### 2.4 Measured cost — this is genuinely cheap

Run on three real scenes of `606f393e` with
`settings.openai_planning_model_cheap` (`gpt-4o-mini`, already
configured): **669 input / 276 output tokens**. Extrapolated to a full
7-scene project: ~1,560 in / ~640 out ≈ **0.06 ¢ per project**.

Use the cheap model. This is mechanical transliteration; it needs no
reasoning, and `openai_planning_model` (`gpt-5.6-terra`) would be waste.

### 2.5 Rule-based transliteration was tried and rejected — do not retry it

A generic library (`indic-transliteration`) plus a hand-written
post-processor was prototyped and **failed on quality**, which is why
this plan is LLM-based. Recorded so nobody re-treads it:

| Rule-based output | Correct Hinglish |
|---|---|
| `men` | `mein` |
| `usak`, `apan`, `unak` | `uska`, `apna`, `unka` |
| `bhut` | `bahut` |
| `shhar` | `shahar` |
| `cale` | `chale` |

The library produces scholarly **Sanskrit** romanization (`unnīsa sau
ikatīsa meṃ unakā`) — diacritics, no schwa deletion. Hindi schwa deletion
is a real, published NLP problem; a 20-line heuristic mangles roughly 1–2
words per line. The LLM got **every one of the above correct** on the
first attempt.

---

## 3. The work

### 3.1 Schema: a display text field per scene

`backend/app/schemas/timeline.py`, on `Scene`:

```python
# Romanized, single-script rendering of `narration_text` for CAPTIONS
# ONLY (caption_romanization.md). None = not romanized; captions fall
# back to `narration_text` verbatim, i.e. today's behaviour.
# NEVER sent to TTS and NEVER indexed by `Shot.narration_span` — those
# both belong to `narration_text`, whose offsets must stay stable.
caption_text: str | None = None
```

Additive and nullable, so every existing timeline stays valid and
unromanized projects render exactly as they do now.

⚠ **Do not put this on `Shot`.** Cue segmentation slices scene-level
text by character span; a per-shot field would need its own offset
mapping and re-introduce exactly the coordinate problem §1.4 avoids.

### 3.2 Where it runs in the pipeline

`DEFAULT_PIPELINE` (`workflow/engine.py:126-137`) is:

```
GenerateTimeline -> ResolveAssets(search) -> SelectMusic -> SelectSfx
  -> Narration -> AwaitApproval -> ResolveAssets(generate)
  -> AwaitReview -> Render -> Complete
```

Romanization needs `scene.narration_text` final, and is needed before
`Render`. **Two viable placements** — pick deliberately:

- **(a) Inside `GenerateTimelineStep`,** as a final planner pass after
  the Asset Planner. Simplest; keeps all LLM planning in one step.
- **(b) A new step between `SelectSfx` and `Narration`.** More
  inspectable (own `workflow_step_attempt` row, own retry/backoff),
  matching how `SelectMusic`/`SelectSfx` are separated.

**Recommend (b)** — it earns its own retry semantics and failure
isolation, and a failure there must NOT be fatal (§3.5).

⚠ Wherever it lands, it must run **after** any script rewrite
(`script/rewrite`) that can change `narration_text`, or the display text
will describe stale words.

### 3.3 The romanization pass itself

New agent, mirroring the existing planner shape exactly:

- `backend/app/prompts/caption_romanizer/v1.md` — the prompt.
- `backend/app/planners/caption_romanizer/` — `schemas.py` + `planner.py`.
- Call through `run_structured_with_repair` (`planners/repair.py:26`)
  with a `validate` callable. **Do not hand-roll retries.**

**Prompt content** (validated against real scenes; keep these rules):

1. Every word in Latin script, as a Hindi speaker would naturally type
   Hinglish (`mein`, `uska`, `bahut`, `chale`, `shahar`).
2. **Same number of words, same order.** Never add, drop, merge, reorder.
3. Words already in Latin (`India`, `Osho`, `famous`) copied **exactly**.
4. Do not translate — script only. Meaning and word choice identical.
5. Danda `।` → period.

**Validator — the part that actually enforces §2.2:**

```
violations = []
if len(out.split()) != len(src.split()):
    violations.append("word count changed: N -> M")
for i, (a, b) in enumerate(zip(src.split(), out.split())):
    if is_latin(a) and a != b:
        violations.append(f"word {i}: Latin word {a!r} was altered to {b!r}")
if re.search(r'[ऀ-ॿ]', out):
    violations.append("output still contains Devanagari")
```

Per-scene, concurrent via `bounded_gather(..., planner_concurrency())`
like the Shot/Asset planners.

⚠ **Known cosmetic gap, accept or fix deliberately:** observed output
had minor spelling drift (`thiin` vs `theen`; `unnis sau ikatees` mixing
conventions). Readable and single-script, so it meets the goal. Tighten
with worked examples in the prompt if it bothers a reviewer — do NOT add
a post-processing rule layer (§2.5).

### 3.4 Captions consume it

`backend/app/renderer/captions.py`:

- `derive_caption_cues` gains the display text as an explicit parameter
  (or reads `scene.caption_text`), falling back to `narration_text` when
  `None`.
- **Timing arithmetic does not change at all** (§2.1). Only the strings
  handed to `CaptionCue.text` and `CaptionWord.text` change.
- **Segmentation must still be computed on `narration_text`**, because
  `char_starts`/`char_ends` index it. Then map segment → the
  corresponding words of `caption_text` **by word index**, not by
  character offset. Character offsets between the two strings are NOT
  comparable and must never be mixed.

⚠ **This is the subtle part of the whole plan.** Segment boundaries are
character offsets into `narration_text`; the display words come from a
different string. The bridge is word index — which only works because of
§2.2's invariant. Write that reasoning into the code.

**Fingerprint:** `cue_list_content_hash` (`captions.py:380`) already
hashes cue text and per-word timings, so romanized cues hash differently
and force exactly one correct re-render. **No new fingerprint parameter
needed** — the same transitive argument as Feature A's own `words`
(style_extensions.md §9 RV-A2). State it in the docstring; do not just
assume it.

### 3.5 Failure policy: never fail the run

If romanization fails or the validator can't be satisfied after repair,
**log a warning and leave `caption_text` as `None`.** Captions then
render exactly as they do today (mixed script) — cosmetically worse, but
a complete video.

This follows `style_extensions.md` §2.7's argued precedent (silently
correct rather than fail loudly when the alternative punishes the user
for a system-side limitation). A captions-only cosmetic improvement must
never be able to destroy a run that has already paid for planning,
assets and narration.

### 3.6 Backfill for existing projects

Because this touches **only caption display text**, existing projects can
be fixed without re-planning: run the pass over the stored timeline,
`append_version(produced_by=..., owns=frozenset({"scenes"}))`, re-render.
No new assets, no new narration, no cost beyond ~0.06 ¢ + one render.

`606f393e` ("OSHO the legend") is the obvious first candidate and the
natural acceptance test.

✅ **The re-render DOES trigger by itself** (corrected by RV-R1,
§8.2 — an earlier draft of this section claimed the opposite and told
you to force it; do not). `backfill_caption_romanization` appends a
timeline version → `TimelineService._persist` calls
`_carry_forward_bindings` → `ShotBindingRepository.carry_forward`
**inserts new rows**, and `ShotBindingModel.updated_at` is
`server_default=func.now()` (`models/shot_binding.py:77-81`). Every
carried binding is therefore stamped *now*, so
`RenderStep.is_satisfied`'s `video_mtime >= latest_binding_update` is
False and the render is correctly seen as stale.

§5 defect 1 is still real — it just does not apply here. Its actual
precondition is a change that appends **no timeline version** at all
(a config edit, a narration-file swap). This one appends a version.

**Acceptance check when the backfill render is watched** (RV-R7,
§8.8): look at caption **line count**, not only readability.
`MAX_CHARS_PER_CUE = 70` is measured against `narration_text`, but what
reaches the screen is now `caption_text`, which runs 7–27% longer in
characters on this plan's own worked examples (44→47, 44→48, 33→42).
With `WrapStyle: 0` a cue near the budget may gain a wrapped line.
Latin glyphs are narrower than Devanagari at the same point size, so
this may wash out entirely — it cannot be settled analytically, only
by looking.

---

## 4. Testing — NO DATABASE, NO LIVE LLM

**Hard rule for this plan, restated from `style_extensions.md` §6 because
this plan touches `backend/tests/`:**

1. **Every test here is a pure function of fixtures.** No live Postgres,
   no live provider. The romanizer's validator, the word-index bridge,
   and the caption serialization are all pure and directly testable.
2. Run explicitly scoped with `--noconftest`, e.g.
   `pytest tests/unit/renderer/test_caption_romanization.py --noconftest -q`.
3. **Never run the full suite or `make test`. Never set
   `PYTEST_TRUNCATE_DB`.** The autouse `clean_database` fixture
   TRUNCATEs every table in the shared Postgres the dev server uses —
   there is no separate test database and there are live projects in it.
4. ⚠ **`--noconftest` leaves test-fixture projects behind.** It disables
   the truncation fixture, which is also the *cleanup*. A previous
   session left 44 empty test projects in the live DB this way, and
   deleting them needed hand-written FK-ordered SQL because
   `DELETE /projects/{id}` is a **501 stub**. If new tests create
   projects, clean them up, or prefer fixtures that never touch the DB.
5. Use a **fake provider** for the romanizer (the `FakePlanningProvider`
   pattern in `tests/unit/planners/`). Never call OpenAI in a test.

**Cases that must exist:**

| Area | Test |
|---|---|
| Validator | word count change → violation |
| Validator | Latin word altered (`India` → `indiya`) → violation |
| Validator | residual Devanagari → violation |
| Validator | clean romanization → no violations |
| Word bridge | cue segmentation on `narration_text` maps to the right `caption_text` words by index |
| Word bridge | per-word **timings are byte-identical** with and without romanization — the §2.1 claim, pinned |
| Fallback | `caption_text=None` produces exactly today's output (regression) |
| Fingerprint | romanized cues hash differently from unromanized |
| Non-ASCII | Hinglish round-trips without mangling (`_escape_ass_text` still holds) |
| Text cards | `derive_text_card_cues` output is **unchanged** by romanization (§1.4) |

---

## 5. Follow-on defects this exposes (not fixed here)

Recorded because they will bite whoever does §3.6, and they are real:

1. **`RenderStep.is_satisfied` watches the wrong signal.** It compares
   video mtime to shot-binding timestamps only, so a change that
   **appends no timeline version** does not mark a render stale.
   ⚠ Narrowed by RV-R1 (§8.2): a change that *does* append a version
   is fine, because carry-forward re-stamps every binding's
   `updated_at`. That is why §3.6's backfill needs no forcing. The
   defect bites config edits and direct file swaps. Observed twice
   in one session: a config change and a narration change each produced
   a 202 + "completed" with **no re-render at all**, and only forced by
   moving `final.mp4` aside. The render fingerprint is correct; the
   staleness gate short-circuits *before* it is ever computed.
2. **`DELETE /projects/{id}` is a 501 stub** (`"project deletion lands
   in M3+"`), and no table has `ON DELETE CASCADE` — deleting a project
   means FK-ordered deletes across 10 child tables. Relevant if §4's
   tests ever create projects.

---

## 6. Sequencing

1. **§3.1 schema field** — additive, nothing reads it yet.
2. **§3.3 romanizer pass + validator**, with fake-provider tests. Not
   wired into the pipeline yet.
3. **§3.4 captions consume it**, with the word-bridge and
   timing-invariance tests. This is where the subtle bug would live —
   test it hardest.
4. **§3.2 pipeline placement** + §3.5 failure policy.
5. **§3.6 backfill `606f393e`** and look at it. That is the acceptance
   test: does the caption line read cleanly in one script, and does the
   word highlight still land on the right word?

---

## 7. Implementation log

### P-R1 — schema, romanizer, captions consume, pipeline (2026-08-28)

**Scope executed:** §3.1, §3.3, §3.4, §3.2 (b), §3.5. §3.6's
`backfill_caption_romanization` helper is in the step module but was
**not** run against `606f393e` (or any live project) — waiting for
review before mutating a narrated timeline / forcing a re-render.

**Changes:**

1. `backend/app/schemas/timeline.py`
   - `ProducedBy.CAPTION_ROMANIZATION` (~line 56) — the first-run stamp;
     NarrationStep overwrites it before anything renders.
   - `Scene.caption_text: str | None = None` (~line 283) — additive,
     captions-only, never TTS, never `narration_span`.
   - `TimelineMetadata.caption_romanization_attempted: bool | None = None`
     (~line 388) — **not in the original §3.1 sketch**. None = not yet
     tried (every existing timeline); True = tried, success or not.

     ⚠ **Corrected by RV-R2 (§8.3).** This entry originally claimed the
     flag was needed because "the engine retries the step until the run
     fails". It does not: `WorkflowEngine.run` checks `is_satisfied`
     **once**, before the step (`engine.py:184-186`), and after
     `outcome == "ok"` moves on without re-checking (`engine.py:254`);
     `_run_with_retry` only loops on `outcome == "retry"`, which this
     step never returns. The flag is still correct, for a different
     reason — **partial success**: if some scenes fail the validator
     they stay `None` with Devanagari intact, so `_nothing_to_romanize`
     is False forever and, without the flag, every later *resume* would
     re-run the LLM and append another no-op timeline version.

2. `backend/app/planners/caption_romanizer/` +
   `backend/app/prompts/caption_romanizer/v1.md`
   - `romanization_violations` (`planner.py:59`) — the §2.2 validator
     as specified (word count, Latin-word identity, residual
     Devanagari including leftover danda).
   - `CaptionRomanizer.plan` (`planner.py:93`) — per-scene
     `run_structured_with_repair`, `bounded_gather` +
     `planner_concurrency()`, Latin-only / already-filled scenes skip
     the LLM. `PermanentError` is swallowed per scene (`caption_text`
     stays None); `TransientError` still propagates so the step can
     retry a rate-limit.

3. `backend/app/renderer/captions.py`
   - Segmentation and timing still run on `narration_text` only.
   - `_token_char_spans` (~line 361) shared by `_word_spans` and the
     display bridge so the splitters cannot drift.
   - `_map_display_words` (~line 407) maps a character span in
     `narration_text` onto `caption_text` **by scene-level word
     index** (the two strings are not comparable by character
     offset). Timings stay the narration token's timings; only
     `.text` is swapped. Word-count mismatch → silent fallback to
     today's mixed-script display, so Feature A cannot desync.
   - `cue_list_content_hash` docstring (~line 481) states the Feature
     A / RV-A2 argument: romanized cue text is already in the digest,
     no new fingerprint parameter.

4. `backend/app/workflow/steps/romanize_captions.py` +
   `backend/app/workflow/engine.py:140`
   - Placement **(b)**: `SelectSfx -> RomanizeCaptions -> Narration`.
   - `is_satisfied` is True when attempted, when no scene has
     Devanagari, **or when `narration_locked`** — that last clause is
     the produced_by landmine. Appending a version on a DEFAULT_PIPELINE
     resume of an already-narrated project would reset `status` to
     DRAFT (`append_version` always does) and, unless re-stamped
     NARRATION, make `_resolve_narration_rows` return None (silent
     video). Existing Hindi projects therefore skip the step; they
     go through `backfill_caption_romanization` (`romanize_captions.py:81`),
     which re-stamps `produced_by=NARRATION` and re-approves.
   - DRY_RUN: no LLM. ⚠ **Changed by RV-R3 (§8.4)** — the step now
     returns `ok` WITHOUT appending a version and WITHOUT stamping
     `attempted`, so a dry-run project neither burns a no-op version nor
     locks itself out of romanization if it is later run for real
     (`is_satisfied` stays False and the step harmlessly no-ops on each
     resume, which is free — no provider call). The `dry_run` branch
     inside `_apply_romanization` stays, because it is what keeps the
     explicit `backfill_caption_romanization` path from calling the real
     provider in dry-run.
   - Cheap model: `OpenAIPlanningProvider(model=settings.openai_planning_model_cheap)`
     (`openai_provider.py:61` gained a `model=` kwarg; default is still
     `openai_planning_model`, every other caller unchanged).

5. Tests (no DB, no live LLM):
   - `tests/unit/planners/test_caption_romanizer.py` — validator cases
     from §4, fake-provider plan/repair/skip/isolate/transient.
   - `tests/unit/renderer/test_caption_romanization.py` — word-index
     bridge, timing invariance (crafted + real fixture), fallback,
     fingerprint, Hinglish ASS round-trip, text cards unchanged.
   - Pipeline order assertions updated in
     `tests/unit/workflow/test_render_only.py` and
     `tests/integration/test_narration_pipeline_ordering.py`.

**Verification performed:**

- `.venv\Scripts\python.exe -m pytest
  tests/unit/planners/test_caption_romanizer.py
  tests/unit/renderer/test_caption_romanization.py
  tests/unit/renderer/test_captions.py
  tests/unit/renderer/test_caption_highlight.py
  tests/unit/renderer/test_text_cards.py
  tests/unit/workflow/test_render_only.py
  tests/unit/providers/test_openai_provider_depiction.py
  tests/unit/providers/test_openai_provider_vision.py
  --noconftest -q` → **75 passed**.
- Whole renderer directory plus the new planner/workflow files:
  `pytest tests/unit/renderer
  tests/unit/planners/test_caption_romanizer.py
  tests/unit/workflow/test_render_only.py --noconftest -q`
  → **189 passed**.
- `ruff check` on every touched file: all checks passed.
- `black --check` clean after formatting.

**Effects / reviewer notes:**

- New projects with Devanagari narration get `caption_text` at plan
  time (cheap model, ~0.06 ¢). Captions render single-script Latin;
  TTS still reads mixed `narration_text`. A romanizer miss logs a
  warning and ships mixed-script captions — never fails the run.
- Existing narrated projects (including `606f393e`) are **unchanged
  until backfill**. Call `backfill_caption_romanization` then force
  a re-render (§5 defect 1: `RenderStep.is_satisfied` will not
  notice a caption-only change).
- Cosmetic spelling drift (`thiin`/`theen`) is accepted per §3.3;
  no post-processing rule layer (§2.5).
- Two extras vs the written sketch, both load-bearing: the
  `caption_romanization_attempted` flag, and the `narration_locked`
  skip on DEFAULT_PIPELINE resume. Please specifically review those.

---

## 8. Review of P-R1 (2026-08-28)

Reviewed against this plan, with every claim re-derived from source
rather than taken from the implementation log. **Verdict: the
implementation is correct and can ship.** The load-bearing parts — the
word-index bridge, timing invariance, the fingerprint argument, and the
pipeline placement — all hold. Findings below are corrections to the
*documentation*, one behavioural nit, and two test gaps. Nothing here
blocks the §3.6 backfill.

### 8.1 Verification re-run independently

| Claim in §7 | Verdict |
|---|---|
| 189 unit tests pass under `--noconftest` | **Confirmed** — re-ran `tests/unit/planners/test_caption_romanizer.py tests/unit/renderer/ tests/unit/workflow/test_render_only.py`, 189 passed in 7.00s |
| `ruff check` / `black --check` clean | **Confirmed** on every touched file |
| §2.1 timing untouched | **Confirmed** — `derive_caption_cues` swaps `.text` only; `start_s`/`end_s` still read `char_starts`/`char_ends` |
| Fingerprint needs no new parameter | **Confirmed** — cue `text` and every `CaptionWord.text` are already in the digest |
| Placement before Narration is safe | **Confirmed** — `NarrationStep` uses `owns={"scenes","metadata"}` and mutates in place, so `caption_text` survives and `produced_by` is re-stamped `NARRATION` |
| Segments never start mid-word | **Confirmed, and structurally guaranteed** — `narration_span` is only ever built from fragment boundaries (`shot/planner.py:383-390`) and `_split_if_too_long` splits only at whitespace. All 19 spans in the captions fixture are word-aligned |
| `" ".join(labels)` loses narration formatting | **Non-issue** — `_escape_ass_text` already collapses newlines to spaces, so the rendered result is identical |
| `render_precondition_gap` now gates on this step | **Safe** — any renderable project is `narration_locked`, so the step reports satisfied and cannot block a render-only call |

### 8.2 RV-R1 — §3.6's "expect to force the re-render" is WRONG (in our favour)

§3.6 and §5 both warn that a caption-only change will not mark the
render stale. **For the backfill path that is incorrect**, and the plan
should be fixed before anyone wastes time moving `final.mp4` aside:

`backfill_caption_romanization` appends a timeline version →
`TimelineService._persist` calls `_carry_forward_bindings` →
`ShotBindingRepository.carry_forward` **inserts new rows**, and
`ShotBindingModel.updated_at` is `server_default=func.now()`
(`models/shot_binding.py:77-81`). So every carried binding is stamped
*now*, `RenderStep.is_satisfied` computes
`video_mtime >= latest_binding_update` → **False**, and the re-render
triggers on its own.

The two no-op re-renders observed earlier in the session were a config
change and a narration change that **appended no version at all** —
that is the actual precondition for the §5 defect, and §5 states it too
loosely. §5 defect 1 remains real; it just does not apply here.

**Action:** correct §3.6 and narrow §5 defect 1 to "changes that append
no timeline version".

### 8.3 RV-R2 — the `caption_romanization_attempted` rationale is wrong (the field is right)

§7 justifies the new field with: *"without it, a validator miss leaves
`caption_text` None and `is_satisfied` stays False forever, so the
engine retries the step until the run fails."*

The engine does not behave that way. `WorkflowEngine.run` checks
`is_satisfied` **once**, before the step (`engine.py:184-186`), and after
`outcome == "ok"` it moves to the next step without re-checking
(`engine.py:254`). `_run_with_retry` only loops on `outcome == "retry"`,
which this step never returns. There is no retry loop to guard against.

**The field is still correct — for a different reason.** On *partial*
success (some scenes fail the validator and stay `None` with Devanagari
intact), `_nothing_to_romanize` is False forever. Without the flag,
**every later resume re-runs the LLM and appends another no-op timeline
version**. That is the real failure mode, and it is a good enough reason
to keep the field exactly as built.

**Action:** keep the field, fix the stated reason in §7 and in the
`TimelineMetadata` comment (`timeline.py:380-388`), which repeats it.

### 8.4 RV-R3 — DRY_RUN stamps `attempted` and appends an empty version

`_apply_romanization` short-circuits the planner under `settings.dry_run`
but still falls through to `append_version`, so a dry-run project burns a
timeline version for a no-op **and** records `attempted=True`. If that
same project is later run for real, `is_satisfied` returns True and its
captions are never romanized.

Impact here is low — this repo's `.env` sets `DRY_RUN=false` — but the
config default is `dry_run: bool = True`, so anyone running defaults hits
it.

**⚠ The fix as first written here was WRONG, and was corrected during
implementation.** The original suggestion — return `ok` from `run`
without appending, and let `is_satisfied` stay False — introduces a
worse bug than the one it fixes: `render_precondition_gap` walks
`DEFAULT_PIPELINE` and returns the **first** step reporting unsatisfied,
which `render_only` turns into a 409. A step that can never report
satisfied under DRY_RUN would **block render-only forever** for every
dry-run Devanagari project. The old stamping behaviour avoided this by
accident.

**Implemented fix:** `is_satisfied` returns True when
`settings.dry_run`, read **live from settings, never stored**. That
gets all three properties at once:

- no no-op timeline version, and no `attempted` stamp;
- the step is out of `render_precondition_gap`'s way;
- flipping `DRY_RUN=false` re-evaluates to False, so the same untouched
  project romanizes on its next real run — which a stored stamp could
  never do.

`run` keeps its own `settings.dry_run` early return as belt-and-braces
for direct invocation, and the `dry_run` branch inside
`_apply_romanization` stays untouched: it is what keeps the explicit
`backfill_caption_romanization` path off the real provider.

### 8.5 RV-R4 — the invariant guard uses a different splitter than the bridge

`_token_char_spans` was extracted specifically so the two splitters
"cannot drift" (its own docstring). But the guard that authorises the
bridge does not use it: `_aligned_display_tokens` compares
`len(scene.caption_text.split())` against
`len(scene.narration_text.split())`, while `_map_display_words` indexes
into `scene_token_ranges`, which comes from `_token_char_spans`.

If those two ever disagreed on a token count, `_word_index_containing`
could return an in-range but **wrong** index and silently mislabel words
— the exact §2.2 failure mode, past its own guard. I probed the
plausible divergence cases (NEL U+0085, NBSP U+00A0, line separator
U+2028, ideographic space U+3000, file separator U+001C, and
repeated/leading/trailing whitespace) and **found no input where they
disagree**, so this is hardening, not a live bug.

**Suggested fix (one line):** have `_aligned_display_tokens` compare
against `len(_token_char_spans(scene.narration_text, 0, len(...)))`, or
assert equality inside `_map_display_words`.

Related, harmless: `_map_display_words`'s
`if len(char_spans) != len(narr_words): return None` is now dead code —
both derive from `_token_char_spans` with identical arguments.

### 8.6 RV-R5 — the flagged landmine has no test

§7 explicitly asks for review of the `narration_locked` skip, and that
clause is the one piece of this change with **no test at all**.
`RomanizeCaptionsStep.is_satisfied` and `backfill_caption_romanization`
are both uncovered; the `narration_locked` behaviour exists only as prose
in a docstring.

`is_satisfied` is DB-free-testable — it touches nothing but
`ctx.timeline_service.get_active`, so a stub context is enough and §4's
no-DB rule is not in the way. Four cases worth pinning:

1. `attempted=True` → satisfied (the partial-failure guard, RV-R2)
2. no scene needs romanization (Latin-only project) → satisfied
3. `narration_locked=True`, Devanagari present, `attempted` None →
   satisfied (**the landmine — a DEFAULT_PIPELINE resume must not
   restamp DRAFT / drop audio**)
4. fresh Devanagari project, not locked → **not** satisfied

### 8.7 RV-R6 — integration test edited but not run

`tests/integration/test_narration_pipeline_ordering.py:75` gained
`"romanize_captions"` in its exact-order assertion. It is DB-gated, so
neither the implementation nor this review ran it. Not a defect — just
unverified. Run it in a real test window, never mid live-test session
(§4 rule 3).

### 8.8 RV-R7 — the cue character budget was tuned on Devanagari

`MAX_CHARS_PER_CUE = 70` is measured against `narration_text`, but what
reaches the screen is now `caption_text`. On this plan's own three worked
examples the romanized string is **7–27% longer in characters**
(44→47, 44→48, 33→42). With `WrapStyle: 0` a cue near the budget may gain
a wrapped line.

Latin glyphs are also narrower than Devanagari at the same point size, so
this may wash out entirely — it cannot be settled analytically. **No code
change proposed.** Add it to §3.6's acceptance check: when the
`606f393e` backfill render is watched, look at caption line count as well
as readability.

### 8.9 RV-R8 — latent constraint worth recording

Stale `caption_text` is **not reachable today**: `narration_text` is
assigned in exactly one place (`scene/planner.py:283`), and no API path
mutates it afterwards. The `_aligned_display_tokens` word-count fallback
therefore never has to save us.

But if a script-edit endpoint is ever added, it **must** clear
`caption_text` and reset `caption_romanization_attempted`. A
same-word-count edit (`1931` to `1932`) would leave the word count
matching, skip the fallback, and display the *old* word on screen with
nothing to catch it.

### 8.10 RV-R9 — `backfill_caption_romanization` has no caller

Surfaced during implementation, outside the original eight findings:
the function exists but nothing in the repo calls it — no API route, no
script under `scripts/`, no test. It is reachable only from an ad-hoc
REPL session.

That is consistent with §3.6 calling it "explicit", and it is not a
defect. But **§3.6's backfill of `606f393e` currently needs a
hand-written entry point**, and whoever runs it must construct a
`RunContext` correctly (session, project_id, repos). If the backfill is
ever meant to be run by someone who did not write it, give it a
`scripts/` entry point first.

### 8.11 Noted, no action

- `owns=frozenset({"scenes", ...})`: `find_additive_violations` returns
  early on an owned list path, so this step is unchecked across the whole
  `scenes` subtree. Same claim `api/projects.py:1564` and `:1724` already
  make, and no narrower path is expressible (there is no per-index
  wildcard). `_record` only ever writes `caption_text`.
- `CaptionRomanizer` passes no `seed` to `run_structured_with_repair` —
  consistent with every other planner (none do), and I5 is satisfied by
  storing the output once rather than by seeding.
- Failure isolation is right: `TransientError` re-raised so
  `bounded_gather` retries and the step can back off; `PermanentError`
  swallowed per scene so a cosmetic miss cannot kill a paid run.

### 8.12 Suggested order for the fixes

Documentation first — RV-R1 and RV-R2 are wrong claims sitting in a plan
future agents will trust:

1. **RV-R1** — correct §3.6 and narrow §5 defect 1.
2. **RV-R2** — correct §7 and the `TimelineMetadata` comment.
3. **RV-R5** — add the four `is_satisfied` cases (no DB).
4. **RV-R4** — one-line splitter hardening.
5. **RV-R3** — dry-run early return.
6. **RV-R7** — fold the line-count check into the §3.6 acceptance test.
7. **RV-R8** — record the constraint next to §1.4.

Then run §3.6's backfill on `606f393e`. Per RV-R1 the re-render should
trigger by itself.

### 8.13 Resolution — all findings closed 2026-08-28

| # | Finding | Status |
|---|---|---|
| RV-R1 | §3.6 wrongly said the re-render must be forced | **Done** — §3.6 rewritten, §5 defect 1 narrowed to "appends no timeline version" |
| RV-R2 | Wrong rationale for `caption_romanization_attempted` | **Done** — §7 corrected, and the `TimelineMetadata` comment (`timeline.py:380`) rewritten to say it guards PARTIAL success across resumes, not an in-run retry loop |
| RV-R3 | DRY_RUN stamped `attempted` and appended a no-op version | **Done, via a different fix than proposed** — the original suggestion would have blocked `render_only` forever; `is_satisfied` now returns True under a LIVE `settings.dry_run` check. See §8.4 |
| RV-R4 | Guard used `str.split()`, bridge used `_token_char_spans` | **Done** — both sides now tokenise with `_token_char_spans`; the unreachable `_map_display_words` guard is labelled and kept |
| RV-R5 | `is_satisfied` had no test | **Done** — `tests/unit/workflow/test_romanize_captions_step.py`, 7 cases including the `narration_locked` landmine and the two DRY_RUN cases from §8.4 |
| RV-R6 | Integration test edited but never run | **Open by design** — DB-gated; run it in a real test window, never mid live-test session |
| RV-R7 | Cue budget tuned on Devanagari | **Resolved by measurement, no code change** — real growth is +2 median / +5 worst-case chars, 0 cues over the 70 budget. See §9 |
| RV-R8 | Latent stale-`caption_text` constraint | **Done** — recorded in §1.4 |
| RV-R9 | Backfill has no caller | **Done** — `backend/scripts/backfill_caption_romanization.py`, preview-by-default |

**Verification:** `pytest tests/unit/workflow/test_romanize_captions_step.py
tests/unit/renderer/ tests/unit/planners/test_caption_romanizer.py
tests/unit/workflow/test_render_only.py --noconftest -q` → **196 passed**.
`ruff check` and `black` clean on every touched file. No database was
touched; no integration or e2e test was run.


---

## 9. Backfill executed — `606f393e` (2026-08-28)

The first live run of §3.6, and the first execution of
`backfill_caption_romanization` against real data.

**Entry point built first (RV-R9):**
`backend/scripts/backfill_caption_romanization.py`. **Preview is the
default** — it runs the real planner (real model, real cost) but appends
no version and rolls the session back, including the `llm_call` rows the
planner inserts. `--apply` is the only mode that writes. That split
exists because this mutates a finished project, and the romanization had
never been seen against real narration before.

**Before:** active v33, `produced_by=narration`, `status=approved`,
`narration_locked=True`, `caption_romanization_attempted=None`,
7/7 scenes Devanagari, 0 with `caption_text`. `final.mp4` backed up to
`renders/final_pre_romanization.mp4` before anything was touched.

**Preview:** 7/7 scenes romanized, **0 problems** — no word-count
change, no residual Devanagari, no altered Latin token. Sample:

```
narration : 1990 में 58 की age में Osho की मौत हो गई।
caption   : 1990 mein 58 ki age mein Osho ki maut ho gayi.
```

`Osho`, `America`, `heart failure`, `Comment`, `government` all copied
through character-for-character. None of §2.5's rule-based failure modes
(`men`, `bhut`, `usak`, `shhar`) appeared — the LLM route holds up on
real narration, not just the three probe sentences.

**Applied:** v33 → **v34**, `produced_by=narration`,
`status=approved`, `caption_romanization_attempted=True`, 7/7 scenes
carrying `caption_text`. Both safety invariants held: the version is
still stamped NARRATION (so render muxes audio) and still APPROVED (so
the gate did not reopen).

**RV-R1 confirmed empirically — this is the useful result.** All 36 shot
bindings carried forward from v33 to v34 with a fresh `updated_at`:

```
v33: 36 bindings, latest updated_at = 17:45:06
v34: 36 bindings, latest updated_at = 20:04:45
final.mp4 mtime                     = 17:57:18
=> video_mtime >= latest_binding_update is False => correctly STALE
```

So `RenderStep.is_satisfied` reports the render stale on its own. The
original §3.6 text (which said to expect to force it) was wrong, and is
now corrected. **§5 defect 1 does not apply to any change that appends a
timeline version** — only to ones that do not.

### 9.1 RV-R7 answered by measurement — no line-wrap risk

The one question that could not be settled on paper. Measured by running
`derive_caption_cues` over v33 (mixed) and v34 (romanized) with the SAME
narration rows, so the display string is the only variable:

| | cues | min | median | max | over 70 | Devanagari cues |
|---|---|---|---|---|---|---|
| v33 mixed | 36 | 20 | 44 | 68 | 0 | 35 |
| v34 romanized | 36 | 24 | **46** | **68** | **0** | **0** |

**Median +2 chars, worst case +5, nothing crosses `MAX_CHARS_PER_CUE`.**

⚠ **§8.8's 7–27% estimate was too pessimistic** and should not be
quoted. It was extrapolated from three short standalone example
sentences; real narration in this style is denser in English loanwords
(`America`, `thallium`, `poison`, `conclusively`, `heart failure`), and
those tokens are copied character-for-character and grow by zero. Only
the Devanagari words expand. The longest cue in the whole video is
unchanged at 68 characters:

```
unhone kaha America ki jail mein unhe thallium poison diya gaya tha.
```

**§2.1 also verified on real data, not just fixtures:** cue count
identical (36 → 36, so segmentation did not move), **0 cues** whose
`start_s`/`end_s` changed, and **0 words** whose per-word highlight
window changed. Swapping the display string genuinely changes nothing
about timing.

**Silent-video check:** the re-rendered `final.mp4` carries an `aac`
audio stream at the same 101.24 s duration as the pre-romanization
backup — the `produced_by=NARRATION` re-stamp did its job.

**Text cards untouched (§1.4):** all six still render as they did
(`90 ROLLS-ROYCE`, `Sheep to Lion`, `RAJNEESHPURAM, OREGON`,
`750+ People Sick`, `1990: Osho Dies`, `No Conclusive Proof`).

The rendered `final.ass` contains **zero Devanagari characters** across
all 294 dialogue lines.

---

## 10. N→1 word grouping — Hindi number words must display as digits

> ⚠ **PARTIALLY SUPERSEDED BY §11.** The storage shape (§10.3's
> `caption_word_groups`), the bridge (§10.4) and the straddle guard
> (§10.5) all stand and are live. But **the LLM must no longer decide
> merging**: §10.3's per-token `covers` contract, §10.6's merging prompt
> rule, and §10.3 invariants 4–5 are withdrawn. They caused 3-of-8 scene
> failures and one silently wrong year on `2deaef0d`. Read §11 before
> touching any of this.

**Status:** planned 2026-08-28, not yet implemented. Follow-on from §9's
live run, which exposed the gap.

### 10.1 The defect

The `606f393e` render ships numbers two different ways in one video:

| scene | narration | caption today | wanted |
|---|---|---|---|
| sc_02 | `उन्नीस सौ इकतीस` | `unnis sau ikatees` | **`1931`** |
| sc_03 | `उन्नीस सौ इक्यासी` | `unnis sau ikyaasi` | **`1981`** |
| sc_01 | `90` | `90` | `90` ✓ |
| sc_04 | `1984`, `750` | `1984`, `750` | ✓ |
| sc_06 | `1990`, `58` | `1990`, `58` | ✓ |

Four numerals render as digits, two as spelled-out words — and the text
cards in the same video read `1990: Osho Dies` and `750+ People Sick`.
That is the *same* internal inconsistency §1.1 set out to remove, just
moved from script-mixing to numeral-mixing.

**Cause.** The narration deliberately spells those two years out, because
ElevenLabs reads `1931` as digit-by-digit gibberish in Hindi but reads
`उन्नीस सौ इकतीस` correctly (2026-08-27 fix). That is right for the ear.
The romanizer then transliterates faithfully — carrying a spoken form to
the eye, where digits are wanted. Neither component is wrong; the
contract between them is missing a case.

### 10.2 Why a prompt change cannot fix this

`उन्नीस सौ इकतीस` is **3** whitespace tokens. `1931` is **1**. §2.2's
validator requires equal token counts, so a model that did the right
thing here would be rejected and the scene would fall back to mixed
script. The invariant itself has to learn about merging.

⚠ Do not "fix" this by relaxing the count check. §2.2 is what stops
Feature A's per-word highlight from silently landing on the wrong word,
and that failure is invisible in a render. Replace it with a *stricter*
structure, not a looser one.

### 10.3 Design — display tokens carry their own source-word count

**LLM output shape** (`caption_romanizer/schemas.py`), replacing the
current bare `caption_text: str`:

```python
class CaptionToken(BaseModel):
    text: str     # ONE display token, no whitespace inside
    covers: int   # how many narration words it replaces, >= 1

class CaptionRomanizerOutput(BaseModel):
    tokens: list[CaptionToken]
```

Emitting tokens rather than a string plus a parallel array removes a
whole class of mismatch: the model cannot tokenise its own string
differently from how the count array says it did.

**Stored shape** (`schemas/timeline.py`, on `Scene`):

- `caption_text: str | None` — unchanged, now `" ".join(t.text)`.
- `caption_word_groups: list[int] | None` — **new**, `[t.covers]`.

Additive and nullable. **`caption_word_groups is None` must run exactly
today's 1:1 path**, so v34 of `606f393e` and every other already-
romanized project keep rendering as they do now until re-backfilled.

**Invariants the validator enforces** (all in code, never the prompt):

1. `sum(covers) == len(narration_text.split())` — every narration word
   is accounted for exactly once, in order.
2. `covers >= 1` — merging only. **1→N is not allowed**, so display
   tokens can only ever be fewer than narration tokens.
3. No `text` contains whitespace.
4. **A merged group (`covers > 1`) must contain no Latin source word.**
   Otherwise the model could absorb `Rolls-Royce` into a neighbour and
   the §2.2 Latin-identity guarantee would quietly weaken.
5. **A merged group's `text` must contain at least one digit.** This is
   the tight expression of "merging exists for numerals only" — it stops
   the model from merging arbitrary words to paper over a count error.
6. Unmerged (`covers == 1`) Latin source words are copied exactly —
   today's rule, unchanged.
7. No residual Devanagari — today's rule, unchanged.

### 10.4 The bridge merges timing

`_map_display_words` today maps narration token index → display token
index as identity. With groups it maps through a flat expansion of
`caption_word_groups` (precompute once per scene, beside
`scene_token_ranges`).

Consecutive narration tokens that map to the same display index become
**one** `CaptionWord`: `text` from the display token, `start_s` from the
first source word, `end_s` from the last. Feature A then highlights
`1931` across the whole `उन्नीस सौ इकतीस` span — which is the correct
reading behaviour, not a compromise.

### 10.5 ⚠ The one genuinely new edge case: a group straddling a cue

This does not exist today and is the reason this change needs care.

Cue spans come from `_segment_span` → `_split_if_too_long`, which splits
at the whitespace run nearest the midpoint. That split can land **inside**
a merged group. A merged `CaptionWord` would then need to start in one
cue and end in the next, which breaks the "a cue owns its words"
structure and can trip `_assert_monotonic_non_overlapping`.

**Decision: if any group straddles a cue boundary, that SCENE falls back
whole to `narration_text`** (mixed script), with a logged warning naming
the scene. Rejected alternatives, recorded so they are not re-tried:

| Option | Why not |
|---|---|
| Render the token in both cues | `1931` visibly appears twice |
| Render only in the first cue | a stretch of audio has no caption at all |
| Per-**cue** fallback | one cue mid-scene flips to Devanagari — worse than a consistent scene |
| Make `_split_if_too_long` group-aware | correct in principle, but segmentation is shared with the non-romanized path; it would move cue boundaries and the render fingerprint for **every** project, romanized or not. Out of proportion |

Scene-level fallback is consistent within what the viewer sees, safe, and
degrades to exactly today's output. If the warning is ever observed in a
real run, the follow-up is group-aware segmentation — but do not build
that speculatively.

### 10.6 Prompt

`prompts/caption_romanizer/v1.md`, edited in place (every agent in this
repo is v1; there is no version-bump convention to follow).

Add one rule: Hindi number words that together express a single numeral —
a year, an age, a quantity — become **one** display token in digits, with
`covers` set to how many narration words it consumed. Everything else is
`covers: 1`.

Worked examples to include:

```
उन्नीस सौ इकतीस में उनका India में जन्म हुआ।
-> [1931 (covers 3)] [mein 1] [unka 1] [India 1] [mein 1] [janm 1] [hua. 1]

1990 में 58 की age में Osho की मौत हो गई।
-> [1990 1] [mein 1] [58 1] [ki 1] [age 1] [mein 1] ...   (already digits: covers 1)
```

The second example matters as much as the first: it teaches that digits
already in the source are **not** merged with anything.

### 10.7 Testing — NO DATABASE, NO LIVE LLM

§4's rules apply unchanged and in full. Restated because this section
adds new test files: `--noconftest` only, on explicitly named files;
never the full suite, never `make test`, never `PYTEST_TRUNCATE_DB`;
nothing under `tests/integration/` or `tests/e2e/`; fake providers only.

| Area | Test |
|---|---|
| Validator | `sum(covers)` ≠ narration word count → violation |
| Validator | `covers: 0` or negative → violation |
| Validator | whitespace inside a display token → violation |
| Validator | merged group containing a Latin source word → violation |
| Validator | merged group whose text has no digit → violation |
| Validator | correct `1931`-style grouping → no violations |
| Bridge | 3 narration words → 1 display word yields ONE `CaptionWord` |
| Bridge | merged word's `start_s` = first source word's, `end_s` = last source word's |
| Bridge | unmerged words keep byte-identical timings (§2.1, re-pinned) |
| Straddle | a group split across a cue boundary → whole scene falls back to `narration_text`, warning logged |
| Back-compat | `caption_word_groups=None` → byte-identical to today's output |
| Back-compat | `groups=[1,1,1,...]` → identical to the `None` path |
| Fingerprint | merged cues hash differently from unmerged |

The back-compat pair is the most important: v34 of `606f393e` is stored
without groups and must not change until it is deliberately re-backfilled.

### 10.8 Sequencing

1. Schema + validator, with fake-provider tests. Nothing consumes it yet.
2. Prompt.
3. Bridge + straddle fallback. **Test this hardest** — it is where a
   silent visual bug would live.
4. Re-run `scripts/backfill_caption_romanization.py 606f393e-... ` in
   **preview** first and read the grouping before applying.
5. Apply, then re-render. Per RV-R1 the re-render triggers by itself.
6. Confirm on screen: `1931` and `1981` render as digits, the highlight
   sweeps the full three-word span, and nothing else moved.

### 10.9 Implemented and shipped (2026-08-28)

Steps 1-3 built by subagent, steps 4-6 run by hand. Live on `606f393e`
as **v35**.

**Three corrections made on top of the subagent's work**, all found by
verifying rather than reading the report:

1. **`needs_romanization` silently skipped every already-romanized
   scene.** It returned False whenever `caption_text` was set - and v34
   had it on all 7 scenes - so re-running the backfill would have
   skipped everything and reported success while changing nothing. It
   now treats a missing `caption_word_groups` as "romanized under the
   old contract, needs upgrading". This is the §10 upgrade path and it
   is load-bearing: without it §10 is unreachable for every project
   romanized before it existed. One existing test pinned the old
   behaviour and correctly failed; replaced with tests for both sides.
2. **`_apply_romanization` dropped `caption_word_groups`** on the way to
   storage (caught by the subagent itself) - groups would never have
   reached the database.
3. **The preview script's `_report()` false-positived on every
   successful merge**, comparing caption word count against narration
   word count. With grouping those are *supposed* to differ. Now checks
   `sum(groups)`.

**`_screen_check` added to the preview.** The word-level report cannot
see §10.5's straddle guard, so a scene could pass every validator and
still render in Devanagari - a regression against the previous output,
not just a missed improvement. Preview now runs the real
`derive_caption_cues` over the candidate scenes and reports what would
actually reach the screen. Use it before any future backfill.

**Result on screen** (`work/final.ass`, 290 dialogue events):

```
events with Devanagari : 0
numerals on screen     : 1931, 1981, 1984, 1990, 58, 750, 90
1931: ONE highlight event, 0:00:11.90 -> 0:00:12.61
1981: ONE highlight event, 0:00:33.79 -> 0:00:34.53
longest cue: 68 chars, 0 cues over the 70 budget
```

Each merged year is a **single** highlight event spanning the full
three-word narration span (§10.4), not three events or a duplicate.
The event count fell 294 -> 290, exactly the 4 words removed by two
3-into-1 merges - an independent check that nothing else moved.

**§10.5's straddle guard did not fire** on real data; both year groups
sat inside a single cue. It remains untested against production input,
so leave it in place and keep `_screen_check` in the preview flow.

RV-R7 still holds after merging: the longest cue is unchanged at 68
characters, and merging can only ever shorten a cue.

---

## 11. Numeral merging becomes deterministic — the LLM stops deciding it

**Status:** planned 2026-08-28, supersedes §10's LLM-side merging.
**§10.3's `covers`-on-every-token contract, §10.6's merging prompt rule,
and §10.3 invariants 4–5 are withdrawn** — see §11.2. §10.4 (the bridge)
and §10.5 (the straddle guard) survive unchanged: the *storage* shape and
the renderer are right, only the thing that decides merging was wrong.

### 11.1 The evidence that §10 was wrong

Measured on `2deaef0d` ("the whey economics", 8 scenes) after §10 shipped:

**Defect A — the model over-merges numerals that are already digits.**

```
sc_02: ('90',  covers 3)  swallowed "90 percent whey"
sc_03: ('250', covers 3)  swallowed "250 percent mehnga"
sc_01: ('2', covers 2) and ('3', covers 2)   -- meaningless
```

Every one of these is correctly rejected by §10.3's validator (`covers`
summed to 43 against 41 narration words; merged groups absorbed Latin
tokens). But with `planner_max_repair_attempts = 1` the model does not
recover, so §3.5's never-fail rule drops the scene to mixed script.

**3 of 8 scenes failed.** Pre-§10 the same scenes romanized cleanly at
1:1, and Osho scored 7/7. §10 made romanization *less* reliable, and it
did so precisely on scripts dense with bare numerals (`90`, `250`, `74`,
`97`, `15`, `30`, `60`) — which is most factual/explainer content.

**Defect B — a merged group can carry the WRONG number, silently.**

```
narration : दो हजार छब्बीस      (do hazaar chhabbis = 2026)
merged    : '2006'
```

Structurally flawless: `covers` sums correctly, no Latin absorbed, the
text contains a digit. It passes **every** §10.3 invariant. `छब्बीस` is
26, not 06. §10.3's "a merged group's text must contain at least one
digit" is far too weak — it checks shape, never value. A wrong year on
screen is worse than a spelled-out one, and nothing in the system can
see it.

Both defects share one root cause: **the LLM was asked to decide
merging.** §11 removes that responsibility rather than prompting harder
against it.

### 11.2 Why a rule-based approach is right HERE, and why that does not contradict §2.5

§2.5 records that rule-based transliteration was tried and rejected. That
conclusion stands and must not be re-litigated — but it does not transfer
to numerals, and the distinction is the whole basis of this section:

| | general transliteration (§2.5) | numerals (§11) |
|---|---|---|
| vocabulary | unbounded | closed, ~110 words |
| the hard part | Hindi schwa deletion — a real, published, unsolved NLP problem | none; `छब्बीस` is 26 in every sentence |
| failure seen | `men`, `bhut`, `usak`, `shhar` | — |
| verifiable offline | no | yes, exhaustively |

Transliteration stays with the LLM. Only numeral merging becomes code.

### 11.3 The split

1. **LLM: plain 1:1 romanization.** One display token per narration word,
   no merging, no `covers` decisions. This is the shape that scored 7/7
   on Osho and 8/8 structurally here — it only started failing when §10
   added merging.
2. **Code: a numeral pass over the result.** Scan `narration_text` for
   runs of Devanagari number words, parse each run to an integer, collapse
   the matching display tokens into one digit token, and emit the
   `caption_word_groups` entry.

```
narration : ... दो हजार छब्बीस। ...
LLM 1:1   : ... do  hazaar chhabbis. ...
numeral   : run [दो, हजार, छब्बीस] -> 2026
          -> one token "2026." covers=3
```

Both defects vanish structurally, not by better prompting: the model
**cannot** over-merge because it no longer decides merging, and `2006`
**cannot** happen because the value is computed.

### 11.4 The parser

A table of Devanagari number words → value: 0–99 (Hindi names these
irregularly, so all hundred are literal entries), plus the multipliers
`सौ` 100, `हजार` 1000, `लाख` 100000, `करोड़` 10000000. Include nukta and
non-nukta spellings (`हज़ार`/`हजार`) — both occur in real scripts.

Standard accumulate algorithm:

```
total = 0; current = 0
for word in run:
    v = TABLE[word]
    if v == 100:                      current = (current or 1) * 100
    elif v in (1000, 100000, 10000000):
        total += (current or 1) * v;  current = 0
    else:                             current += v
value = total + current
```

Worked, and both must be tests:

- `उन्नीस(19) सौ इकतीस(31)` → current 19 → ×100 = 1900 → +31 = **1931**
- `दो(2) हजार छब्बीस(26)` → total 2000, current 26 → **2026**

### 11.5 Three rules that keep it safe — all load-bearing

1. **A run must contain a multiplier** (`सौ`/`हजार`/`लाख`/`करोड़`) to be
   merged. Without this, `एक दो` ("a couple") parses to `3` and renders
   as a digit — a real sentence turned into nonsense. The multiplier
   requirement restricts merging to genuine large numbers, which is
   exactly the year/quantity case this exists for.
2. **A run must be two or more words.** A lone `पचास` stays `pachaas`.
   Collapsing single words would turn ordinary prose into digits and
   change the register of the writing.
3. **A run must parse completely, or it is left alone.** Partial or
   ambiguous matches are never guessed at — the same refuse-to-guess
   stance as `narration_fit.py` and `_resolve_narration_rows`.

⚠ Digits already in the narration (`90`, `250`, `1990`) are **not**
number words, so they never enter a run and are never merged. Defect A
is impossible by construction, not by instruction.

**Punctuation:** a run's last narration word usually carries a danda
(`छब्बीस।`). Take the trailing punctuation from the LLM's own token for
that word, so the merged token is `2026.` and not `2026`.

### 11.6 What changes in the code

| file | change |
|---|---|
| `prompts/caption_romanizer/v1.md` | **remove** the merging rule and the `covers` concept entirely; back to 1:1 |
| `caption_romanizer/schemas.py` | `covers` disappears from the model contract — either a plain token list or back to `caption_text: str` |
| `caption_romanizer/numerals.py` **(new)** | the table, the parser, the run finder. Pure, no I/O |
| `caption_romanizer/planner.py` | drop §10.3 invariants 4–5 (nothing merges LLM-side any more); keep 1:1 count, Latin identity, no-residual-Devanagari; run the numeral pass after validation and derive `caption_word_groups` from it |
| `schemas/timeline.py` | **unchanged** — `caption_word_groups` keeps its meaning |
| `renderer/captions.py` | **unchanged** — §10.4's bridge and §10.5's straddle guard already consume groups correctly |

That the renderer needs no change is the useful signal that §10's storage
shape was right and only its producer was wrong.

### 11.7 Testing — NO DATABASE, NO LIVE LLM

§4's rules apply in full and are not negotiable for this section:
`--noconftest` on explicitly named files only; never the full suite,
never `make test`, never `PYTEST_TRUNCATE_DB`; nothing under
`tests/integration/` or `tests/e2e/`; fake providers only; no Postgres
connection of any kind.

The parser is a pure function, so this is the most testable thing in the
whole feature:

| Area | Test |
|---|---|
| Parser | `उन्नीस सौ इकतीस` → 1931 |
| Parser | `दो हजार छब्बीस` → 2026 |
| Parser | `हज़ार` (nukta) parses identically to `हजार` |
| Rule 1 | `एक दो` → NOT merged (no multiplier) |
| Rule 2 | lone `पचास` → NOT merged (single word) |
| Rule 3 | an unparseable run → left alone, no exception |
| Defect A | narration `90 percent whey` → nothing merged; digits never enter a run |
| Defect B | `दो हजार छब्बीस` merges to exactly `2026`, pinned as a literal |
| Punctuation | `छब्बीस।` → merged token ends `.` not `।` |
| Groups | derived `caption_word_groups` sums to the narration word count |
| Regression | a scene with no number words produces all-ones groups, byte-identical to 1:1 |
| Regression | §10.4 bridge and §10.5 straddle tests still pass untouched |

### 11.8 Sequencing

1. `numerals.py` + its parser tests. Pure, no wiring.
2. Prompt back to 1:1; schema drops `covers`; validator drops invariants
   4–5.
3. Planner runs the numeral pass and derives groups.
4. Re-preview `2deaef0d` — expect **8/8 scenes** romanized and `2026`
   correct. Both are the acceptance criteria; 7/8 is a fail.
5. Re-preview `606f393e` — `1931`/`1981` must still merge. This is the
   regression check that §11 did not lose §10's win.
6. Apply both, re-render.

### 11.9 Implemented and shipped (2026-08-28)

Built by subagent (steps 1-3), applied and rendered by hand (steps 4-6).
Live on `2deaef0d` as **v56**.

**Both §11.8 acceptance criteria met:**

| | under §10 | under §11 |
|---|---|---|
| scenes romanized (`2deaef0d`) | 5/8 | **8/8** |
| `दो हजार छब्बीस` | `2006` ✗ | **`2026`** ✓ |
| Devanagari cues on screen | - | **0** |
| `606f393e` `1931` / `1981` | ✓ | **✓** (regression held) |

**Rendered result** (`work/final.ass`, 289 events):

```
events with Devanagari : 0
numerals on screen     : 15, 250, 30, 60, 74, 90, 97, 2026, 2026.
'2026' : ONE merged highlight, 0:00:34.86 -> 0:00:35.49  "Suppliers ka 2026 ka stock."
'2026.': ONE merged highlight, 0:01:01.71 -> 0:01:02.74  "February 2026."
cue length max 50, 0 over the 70 budget
```

The full round trip now works: the TTS is *given* `दो हजार छब्बीस` and
reads it correctly, while the viewer *sees* `2026`.

**The table was verified independently of the test suite.** 118
hand-written Devanagari entries, where one wrong value is a silently
wrong year on screen and no test the author writes would catch a wrong
expectation. Checked: every entry the two live projects depend on, both
pinned round-trips, the nukta variant `हज़ार` parsing identically to
`हजार`, and all three §11.5 rules - including `एक दो मिनट` correctly
refusing to merge, which is the case that would otherwise turn "a couple
of minutes" into "3 minutes".

**One addition beyond the letter of §11.4, accepted:** §11.5 rule 3
("parse completely or leave alone") had no real trigger, because the
accumulate algorithm always returns *some* integer for a well-formed
run. The implementation added a guard for structurally ambiguous runs -
the same multiplier tier appearing twice (`हजार ... हजार`) - and pinned
it with a test. That is the rule's intent; without it the rule was
decorative.

**Two defects fixed in `scripts/backfill_caption_romanization.py`:**

1. `_screen_check` was silently skipping. It filtered narration rows on
   `timeline.metadata.voice_id`, which is None on any project that never
   had a voice chosen explicitly - matching no rows and reporting "no
   narration rows" instead of checking anything. It now falls back to
   `settings.elevenlabs_voice_id`, the same resolution `NarrationStep`
   uses. A check that silently passes is worse than no check.
2. `_report()` compared caption word count to narration word count,
   which is *supposed* to differ once merging happens (fixed earlier,
   §10.9).

**New: `scripts/edit_narration_text.py`.** Spelling a numeral out for
TTS is now a two-project pattern, and doing it by hand means shifting
every `Shot.narration_span` after the edit point - miss one and captions
desynchronise from audio for the rest of the scene, silently. The script
does the shift, asserts the spans still tile losslessly, and clears the
scene's stale `caption_text` / `caption_word_groups` so a later backfill
picks up exactly the edited scenes.

### 11.10 Known gap - not fixed

`caption_romanization_attempted` is a single project-wide flag, so a
project romanized under §10's weaker rules does not automatically
re-romanize under §11. `needs_romanization`'s "missing group list" check
(§10.9) upgrades pre-§10 scenes, but a scene romanized *by* §10 has
groups and looks current. `606f393e` v35 is in exactly that state: its
`1931`/`1981` merges happen to be correct, so it needs nothing - but a
§10-era project with a wrong merged numeral would keep it. If another
such project turns up, clear its `caption_text`/`caption_word_groups`
with a targeted script and re-run the backfill.
