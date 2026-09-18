# Narration tone via ElevenLabs v3 audio tags

**Status:** Built. Backend + UI landed, tags verified against ElevenLabs docs. Not yet run end-to-end on a real project.
**Branch:** `fun_long_form`
**Started:** 2026-09-17

## Problem

Reels want tone that varies across the take — an explosive open, an investigative
body, a conspiratorial drop at the turn. Today every scene in a project is read in
exactly one voice with exactly one delivery.

There is no per-scene voice control anywhere in the pipeline, and adding one looked
like the obvious fix. It isn't the fix. Tone on `eleven_v3` is not a parameter.

## Why this is achievable without per-scene voice parameters

Three facts make it cheap:

1. **The model is `eleven_v3`** (`backend/app/core/config.py:137`), whose
   differentiator is inline audio tags — `[excited]`, `[curious]`, `[thoughtful]`,
   `[whispers]` — written directly into the narration text.
2. **The text path is a raw passthrough.** The payload is built at
   `backend/app/providers/elevenlabs.py:182` with no sanitization, stripping, or
   normalization between scene text and the API. Tags reach ElevenLabs today.
3. **Batching helps rather than hurts.** Contiguous scenes are joined with `\n` into
   one request up to 3000 chars (`backend/app/timeline/narration_batch.py:92-137`,
   cap at `backend/app/providers/elevenlabs.py:82`). v3 carries emotional state
   *within* a request, so a tag holds across following lines until re-tagged.

## What breaks if you just paste tags into `narration_text`

1. **Captions leak the tags.** `backend/app/renderer/captions.py:262` prefers
   `scene.caption_text` but falls back to `narration_text` when the romanizer
   produced nothing. On the fallback path `[excited]` renders on screen.
2. **Alignment may fail its integrity check.**
   `backend/app/timeline/narration_batch.py:252-254` rebuilds
   `expected = join_batch_text(members)` and compares it against the characters
   ElevenLabs returns, then splits per-scene audio on those offsets. If the returned
   character stream omits tag characters, that equality check fails.
3. **`narration_span` shifts.** Shot references narration by character range into
   `narration_text` (`backend/app/schemas/timeline.py:440`); inserting tags moves
   every downstream span.

The last four commits on this branch were all caption-timing repairs (`offset_s`
always zero, too many captions at once). Breaking alignment is the expensive failure
here, which is why Phase 0 measures before anything is written.

---

## Phase 0 — Probe: does the alignment include tag characters?

Throwaway at `backend/scripts/audio_tag_probe.py`, patterned on the existing
`backend/scripts/hinglish_voice_probe.py`.

Sends two small requests through the real `ElevenLabsNarrationProvider`:

- **A (baseline)** — two short Hindi scenes joined with `\n`, no tags
- **B (tagged)** — the same two scenes, `[excited]` on the first, `[curious]` on the second

The decision it answers:

```
"".join(alignment["characters"]) == text_sent     ->  ?
"[excited]" present in the returned characters    ->  ?
```

Secondary observations captured while it is in there: whether the `\n` joiner
survives v3 intact, and whether v3 accepts or rejects the optional `language_code`
passed at `backend/app/workflow/steps/narration.py:424`.

Artifacts land in `tmp/audio_tag_probe/` (gitignored).

### Phase 0 log

**Run 2026-09-17, exit 0. No edits to the probe were needed. Result contradicted the
prediction: tags ARE echoed in the alignment.**

```
a_clean_pair     exact_match=True  tags_echoed={}
b_tagged_pair    exact_match=True  tags_echoed={'[excited]': True, '[curious]': True}
```

- `"".join(alignment["characters"]) == text_sent` held **True with tags present**.
  The integrity check at `narration_batch.py:252-254` will therefore pass, provided
  `expected` is computed from the *tagged* text that was actually sent.
- Newline joiner survived intact (1 of 1 on both runs), so batching is unaffected.
- `language_code` is `None` in this environment, so the `c_no_langcode` control was
  correctly skipped. The v3-rejects-language_code question remains unanswered and
  unblocking.

**Follow-up: are the echoed tag characters also spoken?** Checked against the
already-downloaded alignment, no extra API call:

```
total audio span: 4.480s
[excited] chars[0:9]  start=0.000  end=0.128  span=0.128s
[curious] chars[23:32] start=1.776  end=1.888  span=0.112s
```

Nine characters in ~0.12s is a marker, not speech — saying "excited" aloud would run
~0.5s. So v3 consumes tags as directives, emits no audio for them, but still reports
them as characters occupying a ~0.12s slice of the timeline.

**Consequence for the design.** This is neither of the two branches sketched in
Phase 2. Because tags echo, `expected` must be built from tagged text or the check
fails; because they occupy character positions, anything downstream that indexes into
narration by character offset sees them. The resolution is to keep tags out of
`narration_text` entirely and confine them to the payload-building and
alignment-splitting layer — see revised Phase 2.

---

## Phase 1 — Listen test

Same script, second mode. Synthesizes the Activa script twice — clean and tagged —
to `tmp/audio_tag_probe/activa_clean.mp3` and `activa_tagged.mp3` for an A/B.

The script is ~1100 characters, well under the 3000 cap, so it goes as a **single
request**: v3 emotional continuity runs across the whole take rather than resetting
at a batch boundary.

### The tagged script

There is no `[explosive]` tag; `[excited]` is the closest v3 supports, and the
explosiveness comes as much from line length as from the tag. Six tags, not fifteen
(`[curious]` carries three of them) — v3 holds state until re-tagged, so tagging every
line fights the model instead of steering it.

```
[excited] 2001 का साल।
जब पूरा भारत, geared scooters चलाता था।
तभी, Honda ने, एक ऐसी scooter उतारी, जिसमें gear ही नहीं था।
नाम था, Activa।

[curious] Reliable, आसान, और बेहतरीन mileage।
जल्द ही, Activa सिर्फ एक product नहीं रहा।
वो, scooter का ही, दूसरा नाम बन गया।
एक वक़्त, Honda का market share, 57 percent तक पहुंच गया था।
हर घर में, एक Activa होना, आम बात थी।

[whispers] लेकिन इसी बीच, TVS ने, चुपचाप, अपनी चालें चलनी शुरू कीं।

[curious] Activa को टक्कर देने के लिए, आई Jupiter.
Young crowd के लिए, आया NTorq.
और फिर, आया सबसे बड़ा दांव।
Electric scooters, iQube.
Honda से बहुत पहले, TVS इस race में उतर गई।

[thoughtful] आज, Honda का हिस्सा, गिरकर 35 percent तक आ चुका है।
वहीं, TVS का हिस्सा, लगभग दोगुना होकर, 28 percent के पार पहुंच गया है।
Activa, आज भी, नंबर 1 है।
लेकिन जो राज, कभी अजेय लगता था।
अब, हर साल, थोड़ा कमज़ोर होता जा रहा है।

[curious] तो क्या, Activa का दबदबा, आख़िरकार खत्म होने वाला है?
Comment करके बताइए।
```

That `[thoughtful]` was `[serious]` when `activa_tagged.mp3` and `activa_expanded.mp3`
were rendered. `[serious]` turned out not to be a documented v3 tag and was swapped
after verification — so those two recordings do not match this script at that one
beat. Everything else in them is current.

Open question for the ear, not the code: `[whispers]` on the चुपचाप line may drop the
energy floor out of a fast-cut reel.

### Phase 1 log

**Run 2026-09-17, exit 0, one invocation. Both reads synthesized.**

```
activa_clean     exact_match=True  tags_echoed={}
activa_tagged    exact_match=True  tags_echoed={'[excited]','[curious]','[whispers]','[serious]'}
```

Newlines preserved exactly (21 sent, 21 returned) on both runs, so the batcher's
joiner is safe at full script length, not just on the two-scene probe.

**The headline number — the tagged read is 13.3s shorter:**

| run | duration | mp3 |
|---|---|---|
| `activa_clean` | 75.280s | 1,205,438 bytes |
| `activa_tagged` | 62.007s | 993,115 bytes |

Same words, 17.6% shorter. The tags are doing real work on delivery pace, which for a
fast-cut reel is a benefit rather than a side effect — but it means tone and scene
duration are coupled, and the timeline planner currently has no idea that adding a tag
will move every downstream scene boundary. Noted for Phase 2.

**Tag spans in the tagged run:**

| tag | char idx | start | span |
|---|---|---|---|
| `[excited]` | 0–8 | 0.000 | 0.427s |
| `[curious]` | 140–148 | 10.128 | 0.336s |
| `[whispers]` | 365–374 | 24.840 | 0.420s |
| `[curious]` | 433–441 | 28.960 | 0.580s |
| `[serious]` | 613–621 | 41.710 | 0.150s |
| `[curious]` | 845–853 | 58.000 | 0.047s |

Three spans exceed the 0.35s heuristic that was meant to catch a tag being read aloud.
That heuristic is the wrong test here and should not be trusted on its own: **if the
tags were being spoken, the tagged read would be longer than the clean one, and it is
13.3 seconds shorter.** The spans are near-certainly pauses at the tone change, not
speech. Settled by ear in the A/B, not by arithmetic.

Compare: `tmp/audio_tag_probe/activa_clean.mp3` against `activa_tagged.mp3`.

---

## Phase 1b — Does tone survive a voice change?

Same tagged script, two further voices, so the comparison is tone-for-tone. Added a
`voices` mode to the probe taking voice ids on argv:

```
.venv/Scripts/python.exe backend/scripts/audio_tag_probe.py voices psUalWK2oKQdtTlpJ5qH FZkK3TvQ0pjyDmT8fzIW
```

### Phase 1b log

**Run 2026-09-17, exit 0, one invocation, no script edits needed.**

Both voices returned `exact_match=True` and echoed all four distinct tags. **The
mechanism is voice-independent** — that is the finding that matters for Phase 2, and
it means the implementation does not need per-voice special casing.

| run | voice | duration |
|---|---|---|
| `activa_clean` | project default | 75.280s |
| `activa_tagged` | project default | 62.007s |
| `activa_tagged_voice_J5qH` | `…J5qH` | 76.887s |
| `activa_tagged_voice_fzIW` | `…fzIW` | 62.805s |

Tag spans stay in the 0.03–0.62s band on both voices, consistent with pauses rather
than speech, but vary per voice (`[serious]` is 0.440s on `…J5qH`, 0.147s on `…fzIW`).

**Caveat — do not over-read the durations.** `…J5qH` at 76.9s lands near the *clean*
default-voice run, which invites the conclusion that it ignores the tags. That is not
established: **no clean baseline was rendered for either new voice**, so a voice that
is simply a slower reader is indistinguishable here from one that under-responds to
tone. Settling it costs two more clean runs (~3550 characters). Not run yet.

Samples: `tmp/audio_tag_probe/activa_tagged_voice_J5qH.mp3`,
`activa_tagged_voice_fzIW.mp3`.

---

## Phase 1c — Does per-scene expansion hold up, and what is the tag vocabulary?

Two questions the gate design (Phase 3) depends on.

**A. Expansion.** Setting tone per scene means a clubbed run of five scenes emits its
tag five times, rather than one tag holding across them. Does repeating it
over-emphasize or pile up dead time?

**B. Vocabulary.** Which tags do anything on Hindi, and what happens to an
unsupported one? `[dramatic]` is deliberately not a documented v3 tag.

### Phase 1c log

**Run 2026-09-17, exit 0, one invocation, no script edits needed.**

**A — expansion is safe. This validates the Phase 3 design.**

| take | duration | tag count |
|---|---|---|
| `activa_clean` | 75.280s | 0 |
| `activa_tagged` (sparse) | 62.007s | 6 |
| `activa_expanded` (every line) | 61.703s | 22 |

Going from 6 tags to 22 moved the take by 0.3 seconds. Tag markers consume 5.543s of
alignment time in total (~9% of runtime), but that is not additive dead time — the
expanded take is still 13.6s shorter than untagged. **Emitting an explicit tone per
scene behaves the same as sparse tagging**, so per-scene expansion costs nothing and
the batching-inheritance trap can be closed by expansion rather than by rule.

**B — vocabulary, and a caution about reading it.**

| tag | duration | delta vs baseline |
|---|---|---|
| _(baseline, none)_ | 4.160s | — |
| `[excited]` | 3.600s | −13.5% |
| `[curious]` | 4.480s | +7.7% |
| `[whispers]` | 3.920s | −5.8% |
| `[serious]` | 3.520s | −15.4% |
| `[sarcastic]` | 3.920s | −5.8% |
| `[dramatic]` *(not a real tag)* | 3.920s | −5.8% |

`exact_match=True` on every run.

**Do not read these durations as evidence a tag "works."** Duration is not tonal
character, and the three tags at 3.920s are not necessarily producing the same audio —
at a fixed 128kbps the mp3 size is a function of duration, so equal sizes here prove
equal length and nothing more.

The finding that does matter: **`[dramatic]`, which is not a supported tag, was
silently absorbed.** It echoed in the character stream, occupied a 0.064s marker,
was not spoken aloud, raised no error — and still shifted the read by 5.8%. So a
typo like `[exicted]` produces no error, no spoken artifact, and no obvious symptom:
just a subtly different default read. **That is the argument for a strict allowlist**,
and it is a stronger argument than any tag's measured delta.

Which tags carry genuine character on Hindi cannot be settled from these numbers.
Samples exist for all seven at `tmp/audio_tag_probe/vocab_*.mp3`.

---

## Phase 2 — Implementation

**Revised after Phase 0/1. Neither original branch applies.** Tags echo in the
alignment *and* occupy character positions carrying real (silent) time. The design
that falls out is simpler than the feared branch:

**Keep tags out of `narration_text` entirely.** They live in a new optional per-scene
field; `narration_text` stays the clean source of truth that captions, fragments and
`narration_span` already depend on.

### Touchpoint map (traced 2026-09-17)

Two things the first draft of this section got wrong, both found by tracing rather
than assuming:

**A. "Confine it to `narration_batch.py`" was false.** `split_batched_alignment` only
runs when `len(job.members) > 1` (`narration.py:469`). A scene that synthesizes solo
bypasses it entirely and is persisted straight through `_persist_slice`
(`narration.py:387-413`). **Tag stripping must happen on both paths**, so it belongs
in a shared helper called from each, not inside the batch splitter.

**B. Cache invalidation is the real gap, and it is not in `narration_batch.py` at
all.** `compute_narration_content_hash` (`elevenlabs.py:128-164`) digests
`f"{text}|{voice_id}|{model}|{output_format}"`, and its call site
(`narration.py:308-315`) passes `text=scene.narration_text`. If tone lives in a
sibling field that never touches `narration_text`, **the hash is blind to it by
construction**: changing a scene's tone without editing its words produces the same
hash, hits the DB row (`narration.content_hash` is unique) or the disk sidecar
fallback, and serves back the old untagged performance. Silent, and exactly the kind
of bug that looks like "the tags don't work."

The fix follows a precedent already in that function: `speed` and `language_code` are
folded into the digest *only when non-default*, so pre-existing rows keep hashing the
same. Tone gets the same omit-if-absent treatment — no migration, no mass
re-synthesis of existing projects.

### Changes required

1. **Field** — add to the domain `Scene` (`schemas/timeline.py:709-744`). **Do not
   name it `tone`**: `CreativeContext.tone` already exists (`timeline.py:1193-1198`)
   as a project-wide planning concept. `narration_tone` or `delivery_tag` avoids a
   vocabulary collision in every future conversation about this code.
2. **Hash** — add an optional `tone` parameter to `compute_narration_content_hash`
   (`elevenlabs.py:128-164`), appended to `digest_input` only when set; pass it at
   `narration.py:308-315`. This is the load-bearing change.
3. **Payload** — `_SynthJob.text` (`narration.py:171`) builds the request via
   `join_batch_text`. Prefix `[{tone}] ` per member there.
4. **Integrity check** — `expected` at `narration_batch.py:252` must be built from the
   *same tagged* join. Phase 0 proved the equality holds with tags present, so the
   check keeps working rather than being weakened.
5. **Strip** — a shared helper that deletes tag entries from the `characters` /
   `character_start_times_seconds` / `character_end_times_seconds` arrays, called on
   both the batched and solo paths before `_persist_slice` writes. **Delete entries;
   do not shift any surviving timestamp** — the pause is genuinely in the audio, so
   untouched timestamps keep text and audio in sync and the remaining character stream
   equals clean `narration_text` exactly. The sidecar written by
   `_write_alignment_sidecar` (`narration.py:178-181`) must hold the stripped version
   too, or `_restore_row_from_disk` (`narration.py:526-573`) resurrects a tagged one.
6. **Cost estimate** — `narration.py:353` estimates via `len(join_batch_text(batch))`.
   Tags add billable characters; use the tagged text or the estimate runs low.

Why the coordinate space matters: every consumer below assumes alignment index `i`
corresponds to `narration_text[i]` — `narration_fit.py:237-300` (the master clock
turning offsets into shot durations), `captions.py:203-268`, `emphasis/planner.py:108`,
`pivot.py:87`, `projects.py:401`, `contact_sheet.py:75`. Step 5 is what keeps that
contract true. Once stripped, none of them learn tags exist, and the recently repaired
caption timing path is untouched.

### Tests

Precedent already exists — `test_narration_persistence.py:171` asserts a different
`voice_id` is a cache miss, `:202` the same for `speed`. Mirror it:

- **tone-only change is a cache MISS** (the bug in B, caught directly).
- Tagged input through `split_batched_alignment`: tags stripped, surviving offsets
  unmoved. Add to `tests/unit/workflow/test_narration_batch.py`.
- Hash inputs with and without tone, in `tests/unit/providers/test_elevenlabs.py`.
- Existing cache-identity tests assume text-only identity
  (`test_narration_step.py::test_identical_scene_text_synthesizes_once`,
  `test_cache_hit_across_projects_never_calls_the_provider_again`) — confirm they stay
  green when tone is absent.

### Blocked on Phase 3

If tone is **author-written**, nothing above touches the scene planner. If tone is
**planner-inferred**, add a field to `ScenePlanOutput` (`planners/scene/schemas.py`),
wire it through `_to_domain_scene` (`planners/scene/planner.py:265-288`), and document
it in `prompts/scene_planner/v1.md`. That schema is OpenAI strict structured output —
all fields required, no defaults — so this is not a free addition. It is a second
argument for the author-written default.

### Still-open risk from Phase 1

Tone changes duration — 13.3s across this script. Scene duration estimation runs
upstream of narration, so changing a tag silently moves every downstream scene
boundary. Needs either a re-estimate after narration or an explicit rule that tone is
locked before timing. Not resolved by any of the above.

### Phase 2 log

**Implemented 2026-09-17.** The tagged/clean split lives entirely in
`NarrationBatchMember`: `text` stays the clean `narration_text`, a new `tone` field
carries the tag, and `tts_text` composes them. Everything that must see the tag
(`join_batch_text`, the char cap in `plan_tts_batches`, `expected` in
`split_batched_alignment`, the billed character count) reads `tts_text`; everything
downstream keeps reading `text`.

| change | file |
|---|---|
| `tone` field, `tts_text`, `tone_prefix`, `strip_tone_prefix` | `timeline/narration_batch.py` |
| `join_batch_text` and batch cap use the tagged text | `timeline/narration_batch.py` |
| slice on tagged length, strip tag from each rebased slice | `timeline/narration_batch.py` |
| `tone` folded into the digest, omitted when absent | `providers/elevenlabs.py` |
| `Scene.narration_tone` + `NARRATION_TONES` allowlist | `schemas/timeline.py` |
| pass `tone` to hash and member; strip on the **solo** path | `workflow/steps/narration.py` |
| `POST /{id}/scenes/narration-tone` | `api/projects.py` |

Both synthesis paths strip: the batched one inside `split_batched_alignment`, the
solo one explicitly in `submit()` — that path never reaches the splitter, which the
first draft of this plan got wrong.

**Correction made during implementation.** The endpoint originally relied on
`Scene._known_tone` firing when the transform assigned `scene.narration_tone`. These
models do not set `validate_assignment`, so a field validator does not run on plain
attribute assignment and an unknown tag would have reached a paid request. The
allowlist check now happens in the endpoint; the field validator remains as a guard
for construction and deserialisation.

**Tests added:** 6 in `tests/unit/workflow/test_narration_batch.py` (tag sent but
absent from `narration_text`; untoned members byte-identical to before; char cap counts
the tag; strip leaves surviving times untouched; a response that dropped the tag is
rejected loudly; per-scene tones). 1 in `tests/unit/providers/test_elevenlabs.py`
(tone changes the hash, absent tone keeps the pre-tone key).

**Integration test added** to `tests/integration/test_narration_persistence.py`,
following the `:171` / `:202` precedent: a tone-only change calls the provider a
second time and produces a second row with a different `content_hash`, both rows
persisting the same clean `narration_text`; re-running with the same tone is a cache
hit. Passes standalone and alongside the rest of the file.

It salts its text with a `uuid4()`, which the older tests in that file do not. That
is not decoration: `narration.content_hash` is globally unique across the table, so
those tests only pass when the shared Postgres has been truncated
(`PYTEST_TRUNCATE_DB=1`). All four fail without it — verified unchanged on a stashed
tree, so this is pre-existing fixture behaviour, not a regression. Salting makes the
new test immune to that pollution.

**Suite status.** `tests/unit`: 1762 passed, 6 failed — all 6 pre-existing and
unrelated (`test_sfx_overlays_diegetic` ×5, `test_director_planner` ×1), confirmed by
stashing this branch's changes and reproducing them identically.

### Not done

- `test_narration_step.py`'s cache-identity tests
  (`test_identical_scene_text_synthesizes_once`,
  `test_cache_hit_across_projects_never_calls_the_provider_again`) still want
  confirming green. They need a truncated DB to run honestly.
- `[whispers]` on the चुपचाप line is still unjudged by ear, and the allowlist still
  wants reconciling against ElevenLabs' v3 tag reference.
- No frontend tests — the frontend has no test runner installed at all.

---

## Phase 3 — Where tone comes from

**Decided 2026-09-17: set per-scene at the approval gate, from the UI.**

Two alternatives were considered and rejected.

*Planner-infers* — rejected on editorial grounds (a model deciding the चुपचाप line
wants a whisper is a call on someone else's writing) and on cost: `ScenePlanOutput`
is OpenAI strict structured output, all fields required, no defaults.

*Author writes inline markers in the submitted script* — designed in full, then
dropped as disproportionate. It required stripping markers at
`GenerateTimelineStep.run()` (the only read chokepoint covering both the Director
prompt at `director/planner.py:94` and the scene slicer), a tag allowlist at upload,
a decision about the `POST /script/rewrite` path mangling markers, and — the real
killer — a rule for what happens when a marker lands mid-scene, since scene
boundaries are LLM-chosen from fragment ranges and a single per-scene field cannot
express two tones.

### Why the gate is better, beyond being easier

1. **Tone is set against audio that has been heard.** `NarrationStep` runs at step 7,
   the gate is step 8. The first read already exists by the time anyone chooses a
   tone — measurement before adjustment, rather than guessing upfront.
2. **It is inside the safe window.** The duration-staleness danger is changing
   durations *after* paid generation (step 9). The gate sits before it, so
   re-reconciliation is free of consequence.
3. **The mid-scene marker problem disappears.** Tone is per-scene by construction
   because the user is selecting scenes, not text positions.
4. **The batching-inheritance trap disappears.** Selecting a group and applying one
   tone writes an explicit value to every scene in it, so no scene depends on
   inheriting tone from a neighbour that might land in a different TTS batch.
5. **No script parsing at all** — no marker stripping, no Director prompt noise, no
   rewrite-path interaction, no upload validation beyond a plain enum on an API field.

### The precedent to copy

`backend/scripts/edit_narration_text.py:182-187` is already this exact shape: a HUMAN
version with `owns=frozenset({"scenes"})` that mutates per-scene narration content and
relies on the content-hash cache so only changed scenes re-synthesize. Its docstring
(`:34-38`) states the mechanism outright. The three `owns={"scenes"}` sites in
`projects.py` (`:2117`, `:2374`, `:2524`) confirm the same narrow-mutation pattern.

### Why it does not fight the engine invariant

`append_version` stamps `produced_by=HUMAN` (`service.py:258`), which makes
`NarrationStep.is_satisfied` false (`narration.py:213-215`, it only checks
`produced_by == ProducedBy.NARRATION`). The resumed engine walks the pipeline from the
top; music, SFX, romanization and emphasis all report satisfied and no-op; narration
re-runs and re-stamps `produced_by=NARRATION`. The invariant at `engine.py:115-129`
holds because those steps all sit *before* narration in `DEFAULT_PIPELINE`.

At the **first** gate the timeline status is `DRAFT`, so
`_resume_after_human_correction`'s `was_already_approved` is False
(`projects.py:742`) and the re-approve branch at `:749-750` is skipped. The run lands
back at the gate, still unapproved. The human must listen again before generation —
which is the correct behaviour and comes for free.

### Sequencing — this is load-bearing

**Phase 2's hash change must land before the endpoint exists.** Without a `tone`
input to `compute_narration_content_hash`, setting tone would correctly un-satisfy
`NarrationStep`, narration would re-run, cache-hit all scenes on an unchanged hash,
and re-append an identical untagged version. A silent no-op that looks exactly like
"the tags don't work."

### Decisions (settled 2026-09-17)

1. **Tone is settable only before the first approval.** Once a timeline has been
   approved, the tone endpoint refuses. This removes the stale-generated-clip problem
   by construction rather than by cleanup — a tone change cannot happen after paid
   generation, so clips can never be left choreographed for a duration that moved.
   Cheapest to build and matches the intent to lock tone early.
2. **Scattered selection warns, does not block.** Non-adjacent scenes still apply, but
   the UI surfaces that a lone changed scene synthesizes alone (RV-Q13,
   `narration_batch.py:27-43`) and picks up a delivery seam at both edges. Retuning one
   scene mid-take stays possible; the cost is just visible.
3. **Strict allowlist; unknown tone values are rejected.** Phase 1c showed an
   unsupported tag is absorbed silently — no error, not spoken, and it still perturbs
   the read. Validation is the only thing that makes a typo visible.
4. **Scope: tone only.** The voice-retry stale-clip path and the music staleness are
   real and documented, but out of this piece of work.

**Field name: `Scene.narration_tone`.** Not `tone` — `CreativeContext.tone`
(`timeline.py:1193-1198`) already claims that word for a project-wide planning concept.

**Allowlist verified 2026-09-17** against
`elevenlabs.io/docs/overview/capabilities/text-to-speech/best-practices`.

**`serious` is not a documented tag and has been removed.** This is the clearest
vindication of not trusting the probe: Phase 1c measured `[serious]` shifting the read
−15.4%, the *largest* delta of anything tested, which read as strong evidence it
worked. The deliberately-invented `[dramatic]` shifted the same line −5.8%. Bracketed
text perturbs delivery whether or not the tag is real, so measured effect is not
evidence of support. Had the list been set from the numbers, `[serious]` would have
shipped — and it is in the Phase 1 script above, which produced `activa_tagged.mp3`.

The shipped list is **delivery tones only**, deliberately narrower than the published
set. The docs also list one-shot vocal sounds (`[laughs]`, `[sighs]`,
`[clears throat]`), sound effects (`[gunshot]`, `[applause]`) and pauses
(`[short pause]`). Those are performances at a moment, not a manner of speaking that
holds across a scene — prefixing `[laughs]` inserts a laugh, it does not make the
scene laughing. Twelve tones ship: `excited`, `curious`, `thoughtful`, `surprised`,
`happy`, `sad`, `angry`, `annoyed`, `appalled`, `sarcastic`, `mischievously`,
`whispers`.

Still **not documented** by ElevenLabs, so still unknown: what an unrecognised tag
does, whether tag support is reliable on Devanagari, whether tags echo in the
`/with-timestamps` alignment (Phase 0 measured that they do), and any guidance on tag
density (Phase 1c measured that expansion is safe). Four behaviours this
implementation depends on that rest on measurement rather than contract.

### Phase 3 log

**UI built 2026-09-17.** `frontend/src/components/NarrationTonePanel.tsx`, mounted in
`pages/AssetReviewGate.tsx` above the shot/scene list.

| change | file |
|---|---|
| `Scene.narration_tone`, `NARRATION_TONES` const | `frontend/src/lib/types.ts` |
| `setSceneNarrationTones` | `frontend/src/lib/api.ts` |
| `useSetSceneNarrationTones` | `frontend/src/lib/queries.ts` |
| the panel | `frontend/src/components/NarrationTonePanel.tsx` |
| mount | `frontend/src/pages/AssetReviewGate.tsx` |

**It reads `timeline.scenes`, not `progress.scenes`, and that is load-bearing.** The
gate's grouped scene list only renders above `SCENE_GROUP_SHOT_THRESHOLD` (40 shots),
and a 40-50s short-form reel never reaches it — hanging the control off that list
would have hidden it for exactly the format this feature was built for. `SceneProgress`
also carries no tone field; the timeline does, so no backend serializer change was
needed.

Decisions 1-3 are all visible in the UI rather than left to the API to enforce: the
panel disables itself with an explanation when `timeline.status === "approved"`
(Decision 1), warns when the selection is not one unbroken run (Decision 2), and
offers only `NARRATION_TONES` plus "Default read" so an unknown tag is unreachable
(Decision 3). The 409 and 422 remain as the real guards; the UI just stops the user
walking into them.

There was no existing multi-select anywhere in the app, and no UI control for
`retryNarration`/`retryMusic` either — those hooks exist but nothing renders them. The
mutation follows `useRegenerateFailedInScene`'s shape (202 trigger,
`invalidateAfterTrigger` on `onSettled`, `.mutate()` never awaited) and the toast/error
idiom is copied from `handleRegenerateFailed`.

`tsc -b` clean, `oxlint src` clean for the new files, `npm run build` succeeds.

---

## Cost

~200 characters of ElevenLabs credit for the probes, ~2200 for both full reads.
Three API calls. No DB writes, no seeding, nothing touching shared Postgres.

---

## Adjacent fix — unbounded search retry

Not part of the tone feature. Found while diagnosing "I set one tone and it went off
searching assets", which turned out not to be the tone endpoint's doing.

### What was wrong

A `TransientError` during the free asset search leaves a binding `pending` on purpose,
so a later run can retry it (`resolve_assets.py`, the per-shot `except TransientError`
branch). `binding.attempts` was incremented there and **read by nothing**. Three
behaviours then compounded:

1. `ResolveAssetsStep(search).is_satisfied` is False while ANY binding is `pending`,
   and the check is project-wide, not scoped to whatever changed.
2. `TimelineService._carry_forward_bindings` copies `pending` verbatim onto each new
   timeline version, so the stuck state survives every version bump.
3. `WorkflowEngine.run()` re-asks every step from the top on every resume, and
   `resolve_assets_search` sits at index 1 — ahead of music, SFX, captions, emphasis
   and narration.

So one permanently-unresolvable shot re-ran the entire free search pass on **every**
engine resume, including resumes triggered by something completely unrelated — a
narration tone edit, a voice retry, narration's own duration reconciliation. There is
no query cache in front of the providers, so each repeat was real
Pexels/Wikimedia/Commons traffic **plus two billed OpenAI calls** per fresh candidate
(a vision plausibility check and a focal-locate).

Measured on project `c2b422f5`: 3 bindings sat `pending` across v6, v7, v8, v9 and
v10, re-searching on each. The tone click was simply the first resume the user watched.

Worth noting it was already a dead end: the approval gate's terminal set is
`("resolved", "generated")`, so a `pending` shot cannot be approved anyway. The system
was refusing to move forward *and* not saying so.

### The fix

`settings.max_search_attempts_per_shot` (default 3, mirroring the existing
`max_generation_attempts_per_shot` convention) and a pure
`search_attempts_exhausted(attempts, generation_permitted)` in `resolve_assets.py`.
Once the cap is hit the binding becomes `failed`, which is terminal — so
`is_satisfied` goes True, the loop stops, and the spend stops.

**`failed` was chosen because the escape hatch already exists.** `AssetReviewGate.tsx`
renders a per-scene "Regenerate failed (cost)" button gated on `scene.failed_shots > 0`.
A shot that gives up lands directly in a control the user already has, with its real
`last_error` attached, instead of retrying in silence.

The generation pass is exempt. It parks bindings on `pending` while a fal.ai video job
is in flight, setting that state directly rather than through the transient handler, so
its `attempts` never climbs — capping it would be a different decision about a
different lifecycle, and is not the failure that was measured.

Rejected: making unrelated corrections resume from a specific step instead of walking
the pipeline. Re-asking every step is the engine's resumability design; the bug was an
unbounded loop, not the walk.

### Tests

`backend/tests/unit/workflow/test_search_attempt_cap.py`, 7 cases — under the cap
keeps retrying, at the cap gives up, past the cap stays given up, the generation pass
is never capped, and the cap reads from config rather than a literal. No DB needed.

### State when this landed

Project `c2b422f5` had already self-cleared (0 pending on v12), so the tone workflow is
unaffected there. One project remained affected — "The GDP Dileama", 22 bindings
pending, **all at `attempts=1`**, every one carrying
`openai depiction check transient error: Error code: 429`. So they get two more tries
before being marked failed, which is the right outcome for a rate limit: transient
enough to be worth retrying, bounded enough to stop.

That those are 429s rather than genuine no-results is its own signal — OpenAI
rate-limit pressure during the search pass is worth looking at separately.

---

## Bug — A/V drift on the first rendered draft (2026-09-17)

Reported as "all the visual cues are not aligned, the voice is slow while the video is
fast" on the first real render after tone was applied to all 8 scenes. **Caused by this
feature**, specifically by a stated design decision in Phase 2 that was wrong.

### What was wrong

Phase 2 said, emphatically: *"Delete the entries; do not shift any surviving
timestamp. The pause is genuinely in the audio, so leaving every surviving timestamp
untouched keeps text and audio in sync."*

The first half is right and the conclusion does not follow. The tag's characters carry
real marker time at the head of the request, so deleting them without absorbing that
time leaves `character_start_times_seconds[0]` sitting at the tag's END — measured
0.050s to 0.339s across the eight scenes — while the scene's audio file still begins
at 0.

`narration_fit._spoken_durations_for_scene` (`narration_fit.py:288-295`) derives a
scene's span as `scene_end_time - character_start_times_seconds[span[0]]`. So every
toned scene reconciled to LESS video than its audio actually runs, and the shortfall
accumulated down the timeline: ~1.24s over one 60-second reel. The picture ran ahead;
the voice fell behind.

The alignments themselves passed every existing check. The 1:1 character contract held,
the text-equality check held, the tests passed — because nothing tested the invariant
that was actually broken: **a scene's alignment must begin at the same instant its
audio file does.**

### The fix

`strip_tone_prefix` now absorbs rather than drops: the tag's entries go, and the first
surviving character's `start` is pulled back to where the tag began. Everything else is
untouched.

This is the trade `split_batched_alignment` already makes for the joiner — "excluded
from each scene's alignment and absorbed into the previous scene's last-character end
time". The same pattern was sitting in the same file, in a docstring, and was not
followed. Cost is identical in shape: the first word's caption may appear up to a third
of a second early — bounded and local — against cumulative drift, which is neither.

`strip_tone_prefix` also now raises rather than returning an empty alignment when the
prefix would consume everything.

### Data repair

The 9 affected `narration` rows were repaired in place (`start[0] -> 0.0`) along with
their `.alignment.json` sidecars. In-place was necessary, not merely cheaper: the
content hash does not change when the bug is fixed, so those rows would have stayed
cache hits serving the bad alignment forever, and `_restore_row_from_disk` would have
rebuilt them from the bad sidecars. The audio was always correct — only the timing
metadata was wrong. Contained to one project, "The scooty wars"; no other project has
ever had a tone set.

The timeline still holds shot durations reconciled from the bad alignments, so it needs
one more `NarrationStep` pass to re-derive them. That pass cache-hits all 8 scenes and
costs nothing.

### Tests

Three new cases in `test_narration_batch.py`, and an existing one corrected — it had
asserted the buggy behaviour (`start[0] == 1.0`) and passed, which is exactly how the
bug shipped. The new cases pin the invariant directly: the stripped alignment starts at
0, the total span is preserved so no drift accumulates, and nothing but that first
start moves.

---

## Bug — render could not find the audio it had just synthesised (2026-09-17)

```
timeline is produced_by=narration but no narration row exists for scene sc_01
(content_hash a82d3e23...) - cannot mux audio that was never persisted
```

Caused by this feature. `tone` was added to `compute_narration_content_hash` and
**one of its three call sites was updated**:

| call site | passed `tone`? | |
|---|---|---|
| `workflow/steps/narration.py` | yes | wrote rows under the with-tone key |
| `workflow/steps/render.py` | **no** | read under the without-tone key -> not found |
| `projects/deletion.py` | **no** | cross-project cache-ownership transfer; latent |

Confirmed by computing both variants against the failing scene: the hash in the error
is exactly the without-tone key (0 rows), and the real row sits under the with-tone key
(1 row). The audio was on disk and in the database throughout. The refusal itself was
correct — that code deliberately will not mux a timeline whose narration it cannot
locate, rather than emit a silent video.

### Why the tests did not catch it

There was a test proving tone changes the hash, and an integration test proving a tone
change re-synthesises. **Both exercised the writer.** Nothing asserted that the reader
computes the same key, which is the only property a cache actually needs.

### The fix

Not "remember to pass tone in three places" — that drifts again the next time a field
is added, exactly as it had already drifted for `speed` and `language_code`. The
assembly moved into `app/timeline/narration_key.py`, which takes the **scene** rather
than its fields, so a caller cannot omit one by forgetting it exists. All three sites
now call it. Adding an eighth input is one line.

`tests/unit/timeline/test_narration_key.py` includes a structural test that fails if
any module under `app/` calls `compute_narration_content_hash` directly again. That is
the test that would actually have caught this.

### Verified

Draft re-rendered on timeline v60: **video 61.233s, audio 61.300s — a 0.067s gap**,
under two frames at 30fps. The previous draft was 58.733s video against 60.900s audio,
a 2.167s gap. Note the totals moved because the voice was changed in between; the
number that matters is the gap.

### Standing back

Three defects from this feature, all the same mistake: something shared was changed and
only the path in mind at the time was verified. The alignment absorption, the audio
tail, and now the hash signature. Two of the three fixes were themselves written
against measurements that turned out to be wrong (`transition` vs `transition_out`, a
hash check missing `speed`). The structural test above is the first change here that
makes a whole class of this impossible rather than fixing one instance of it.
