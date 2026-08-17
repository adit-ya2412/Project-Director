# 14 — Burned Captions: Implementation Plan

> **Status:** Built and verified, 2026-08-17. Written 2026-08-16. See **§10 Verified corrections** before reading §0/§3.1/§4.2, which that addendum supersedes in two places, and **§11 Implementation summary** for what shipped and how it was verified.
> **Decision it implements:** [D2](13_Implementation_Guide.md) — captions come from script text plus TTS timings, never from transcribing our own narration audio.
> **Prerequisite already met:** [D1](13_Implementation_Guide.md) — ElevenLabs returns character-level alignment with the audio.

> ## ⚠ Read before running anything
>
> **`pytest` truncates the shared Postgres database.** The test suite and the dev server point at the same database, so a full suite run **deletes every real project in it**, including the caption fixture this plan depends on (§0). This is not hypothetical — a live project was destroyed this way once already (2026-08-15, project `c904cb39`), and three separate rounds of phantom test failures were traced to two `pytest` processes racing each other over the same tables.
>
> Two rules follow, and both matter for this work specifically:
>
> 1. **Export the fixture before running the suite** (§0). Once exported to `tests/fixtures/`, it survives truncation and can be reseeded. Until then it exists in exactly one place and one `pytest` invocation destroys it.
> 2. **Never run two `pytest` processes at once**, and never run one while a live test session is using the dev server. Whoever runs the suite owns the database for its full ~12 minutes.

---

## 0. The fixture: project `71e4758a-1a05-4a47-982b-c97861777d20`

Use this project — *"A beutiful desease"*, `status=completed`, with a real `renders/final.mp4` on disk. Inspected 2026-08-16; the numbers below are measured, not assumed.

| | |
|---|---|
| Timeline | v27, `produced_by=narration`, `status=approved` |
| Structure | **6 scenes, 19 shots**, `total_duration_s=58.329` |
| Transition durations present | **`0.0, 0.3, 0.4, 0.5`** — four distinct values |
| Narration rows | **18** = 6 scenes × **3 different voices** |
| Alignment | character-level, all 18 rows, three parallel arrays of equal length, non-empty |

**Why this is a strong fixture for §3.1 (the drift bug).** Sum the per-scene narration spans for one voice and you get **~67.1s of audio against a 58.329s video** — a **~8.8-second** gap, produced by 18 transitions overlapping their adjacent shots. So a caption track built on a naive cumulative sum of scene durations is not subtly wrong by the end; it is nearly **nine seconds** adrift on a one-minute video. That makes the failure mode in §3.1 loud and trivially detectable here, which is exactly what you want from the test that guards it. The four distinct transition durations (including `0.0`) mean a correct implementation cannot fake it with a single constant.

**Why it is strong for §3.3 (segmentation).** Scene length varies from 96 characters over ~6.3s (`sc_03`) to **305 characters over ~22.9s** (`sc_04`). That long scene is precisely the "mathematically perfect cue nobody can read" case — it must break into multiple cues, and it is right there in real data.

**Where it is weak: §3.2 (the font problem).** The script is **almost entirely Latin**. Only `sc_02` contains Devanagari, and only **4 characters** of it out of ~880 across the project. So this fixture will *not* meaningfully exercise Devanagari shaping, conjuncts, or font fallback — it will render fine in a Latin-only font and tell you nothing. **Do not treat a clean render of this project as evidence the font question is settled.** Verifying §3.2 needs either the earlier mixed-script Hinglish project or a purpose-made scene with real Devanagari sentences.

**One trap this fixture exposes that the plan would otherwise have missed:** there are **three narration rows per scene**, one per voice (`T3s9anIvGvoeogXyFyMt`, `SLa3GDQHUGaRpH5GNvFL`, `0muxiGNHAVvmM1qWRtyV`) — the residue of voice retries (N1). Cue derivation must select the row matching the **timeline's current voice**, not merely "the narration row for this scene". Selecting naively yields captions timed to a voice that is not in the video — and since all three voices speak the same text, the captions would look plausible and be silently out of sync. The same scene's audio runs 13.0s in one voice and 10.8s in another, so the error is seconds wide.

---

## 1. Why this is mostly assembly, not invention

Three things already in the codebase do the hard part, and none of them were built for captions:

- **`narration.alignment` stores the RAW ElevenLabs alignment object** (`app/models/narration.py`) — three parallel arrays: `characters`, `character_start_times_seconds`, `character_end_times_seconds`. Deliberately the raw object, never `normalized_alignment`. Given any character offset into a scene's narration text, its exact start and end second is a direct lookup.
- **`Shot.narration_span` is already a character-offset pair** into its scene's `narration_text`. The D1 correction (timings are character-level, not word-level, as originally written) turned out to make captions *simpler*, because the Timeline already speaks in character offsets.
- **`app/planners/fragments.py::split_narration_fragments`** produces deterministic, lossless, exactly-tiling character spans (`NarrationFragment.start/end`). It was built to stop planners doing character arithmetic, but a caption cue list is close to the same shape: contiguous spans of narration text with boundaries a human would recognise.

So the pipeline is: **character span → seconds via stored alignment → ASS cue**. No new timing source, no forced alignment, no transcription. D2 holds by construction.

---

## 2. What exists today

**Nothing functional.** `burn_captions: bool = True` and `caption_font: str = "Inter"` sit in `app/core/config.py` and **no render code path reads either one**. No ASS generation, no `subtitles=` filter wiring.

Two inherited inconsistencies to clean up as part of this work:

- **Docs and config disagree.** Phase M8's notes say `BURN_CAPTIONS=false` and "the ASS generation path is not built"; the config default is `True` and `.env` sets `BURN_CAPTIONS=true`. Both are harmless only because nothing consumes the value — but it reads as "captions are on" to anyone skimming.
- **These are one of the two dead-config items flagged in the R2 fingerprint audit.** See §6 — wiring them in without touching the fingerprint reproduces the R2 bug exactly.

---

## 3. The three real problems

Everything else here is mechanical. These three are where the work actually is.

### 3.1 Scene-relative time is not video time

Narration is synthesized **per scene** (`narration.scene_id`), and each scene's alignment array starts at `0.0` for **that scene's own audio file**. A cue built naively from alignment seconds will be correct for scene 1 and progressively wrong for every scene after it.

Worse, the offset is not a running sum of scene durations, because **transitions overlap adjacent shots (D5)** — a 0.4s dissolve between two 3.0s shots yields 5.6s of video, not 6.0s. `app/timeline/duration.py::compute_shot_start_times` already owns that arithmetic and is the only correct source for where anything starts.

**This is the single most likely way to get captions subtly wrong**, and it fails in the most expensive way: not with an error, but with subtitles that drift a little further out of sync with every scene, looking like a vague "audio sync feels off" problem rather than a caption bug. It is the same failure class the guide already warns about for transition arithmetic.

**Before writing any code, establish empirically:** how does `RenderStep` actually mux narration — one concatenated audio track, or per-scene segments placed at computed offsets? Whichever it is, caption time must be derived from *that same* offset computation, reusing `compute_shot_start_times` rather than recomputing it. Do not infer this from the docs; read the render path and confirm against a real rendered file.

### 3.2 `Inter` cannot render your script

`CAPTION_FONT` defaults to `Inter`, chosen before the project's language was. **Inter has no Devanagari coverage** (Latin, Greek, Cyrillic only). The actual working script is mixed-script Hinglish — Devanagari with Latin loanwords — so burning captions in Inter produces tofu boxes for every Devanagari run, on the one video this feature exists to serve.

This needs an explicit decision, not a default:

- A font with genuine Devanagari + Latin coverage (Noto Sans Devanagari is the obvious candidate; Mukta and Hind are alternatives designed for exactly this pairing).
- **How the font reaches FFmpeg** is its own problem, and a determinism problem: relying on the host's installed fonts means the same Timeline renders differently on two machines, which violates I5. The font file should be vendored into the repo and passed explicitly (`fontsdir` on the `subtitles=` filter), so the render depends on a file we control and can hash — not on what happens to be installed.
- Verify the chosen font renders **conjuncts** correctly (क्यों, स्थ), not just individual glyphs. This is a real failure mode with incomplete Devanagari fonts and is only visible by looking at rendered output.

### 3.3 Exact timing is not the same as readable captions

Character-level alignment gives a mathematically exact start and end for any span. That is necessary and not sufficient — a cue holding a 25-word sentence on screen for nine seconds is technically perfectly synced and unreadable.

Cue segmentation is a **creative** decision that needs rules written down:

- Maximum characters per cue (two lines is the conventional ceiling for vertical short-form).
- Minimum on-screen duration, so a short fragment doesn't flash.
- Maximum, so a long pause doesn't strand a cue on screen.
- What to do when one shot's narration span is much longer than one readable cue — split it, and split on what boundary?

`split_narration_fragments` is the natural starting point (it already splits on sentence-ish punctuation, deterministically and losslessly) but its fragments were sized for planner prompts, not for reading. Expect to need a second pass that merges very short fragments and splits very long ones against a character budget. Keep that pass deterministic and pure — same input, same cues, always.

---

## 4. Design

### 4.1 Where the code goes

A new module, `app/renderer/captions.py`, owning exactly two things:

1. **Cue derivation** — `(Timeline, narration rows) → list[CaptionCue]`, where a cue is `(start_s, end_s, text)` in **final-video time**. Pure function, no I/O, no config reads. This is where §3.1 and §3.3 live and where nearly all the tests point.
2. **ASS serialisation** — `list[CaptionCue] → str`. Pure. Deterministic formatting: fixed decimal precision, stable ordering, no timestamps or locale-dependent number formatting anywhere in the output.

The renderer then writes that string to a file and adds one `subtitles=` filter to the graph. Keeping derivation pure and separate from FFmpeg is what makes this testable without rendering anything.

### 4.2 Cue derivation, step by step

1. For each scene, load its narration row and raw `alignment`.
2. Build the cue spans over that scene's `narration_text` (§3.3's segmentation rules).
3. Map each span's character offsets to seconds via `character_start_times_seconds[start]` and `character_end_times_seconds[end-1]`.
4. **Shift into video time** using the same offset arithmetic the renderer uses (§3.1).
5. Concatenate across scenes, assert cues are monotonic and non-overlapping, and fail loudly if they are not — a violated invariant here means the offset logic is wrong, and silence would ship drift.

### 4.3 FFmpeg wiring

- One `subtitles=` filter on the final video stream, after composition.
- **Windows path escaping** — `subtitles=C\:/path/x.ass`. Flagged in the guide's own day-one advice as a known trap; the drive-letter colon must be escaped or the filter fails in a way that is easy to misread.
- **Drafts get no captions** (guide: "480p, no captions"). Drafts exist for pacing and asset checks; captions are a final-render concern and slow the fast path down.
- Font passed explicitly via `fontsdir`, per §3.2.

---

## 5. Determinism (I5)

Rendering must stay a pure function — same Timeline, same assets, same settings, same FFmpeg, byte-identical output. `tests/integration/test_render_determinism.py` proves this today with a literal `sha256` comparison and it must keep passing.

Caption-specific hazards:

- No `datetime.now()` anywhere in the ASS file (some ASS writers emit a generation timestamp by default — do not).
- Fixed float formatting for cue times; never locale-dependent.
- Stable, sorted cue ordering.
- The font must come from a vendored file, not host fontconfig (§3.2) — otherwise the same input renders differently on two machines and I5 is quietly false.

---

## 6. The fingerprint (do not skip this)

`compute_render_fingerprint` decides whether to skip a render and serve the existing file. **Every input that changes output bytes must be in it.** This was the exact R2 defect: the music gains were read at mux time and not fingerprinted, so changing them served the previous render as if I5 held. Both gains are now *required* kwargs specifically so the next such input cannot be forgotten silently.

Captions are the next such input. Add, at minimum:

- whether captions are burned at all (`burn_captions`)
- the resolved font identity — the **vendored font file's content hash**, not its name, so swapping the file changes the fingerprint
- a hash of the **rendered cue list** (times and text), which covers script edits, re-narration with a different voice, and any change to the segmentation rules in one value

The R2 audit already names this as the landmine. Wiring captions in without doing this reproduces that bug precisely, and it presents as "I changed the font and nothing happened."

---

## 7. Testing

**Step zero, before any of this: export the fixture** (§0's warning). `backend/scripts/export_test_project.py` writes a project to `tests/fixtures/` — timeline, narration rows with their alignment, bindings and media — so it survives the truncation every suite run performs. Project `71e4758a` currently exists in exactly one place; the first `pytest` after this document is written destroys it unless it has been exported. Check the export round-trips (seed it back and confirm scene count, narration rows and the active voice) before trusting it, since the exporter has had real defects before: it once wrote bindings for every superseded version, and the seeder renumbered versions without remapping them.

Then:

- **Cue derivation, unit** — against the real stored alignment from §0, never a synthetic one. Synthetic alignment arrays are uniform in a way real TTS output never is, and they hide exactly the bugs worth catching.
- **The multi-scene offset case explicitly** (§3.1) — this is the test that earns its keep. Assert the *last* scene's first cue lands at the right second, because that is where the ~8.8s drift accumulates in the fixture. A test that only checks scene 1 passes under a completely broken implementation.
- **Voice selection** (§0's trap) — assert cue times come from the narration row matching the timeline's current voice. The fixture has three voices per scene differing by seconds on the same text, so a naive "first row for this scene" implementation produces plausible, silently wrong captions; this test is what catches it.
- **Determinism** — same input, byte-identical ASS, twice.
- **Segmentation rules** — no cue exceeds the character budget, none shorter than the minimum duration, cues tile without overlap. `sc_04` (305 chars / ~22.9s) is the natural case.
- **Render smoke test** — one short real render with captions on, ffprobed.
- **Devanagari, separately and by eye** — §0 makes clear the current fixture cannot prove this: 4 Devanagari characters project-wide. Use the earlier mixed-script Hinglish project or a purpose-made scene, and look at an actual frame. No assertion catches tofu boxes or broken conjuncts.

---

## 8. Open decisions — needed before building

Each carries a recommendation. They are recommendations, not decisions: 2 and 3 in particular are creative calls that belong to the user.

### 8.1 Cue granularity → **recommend per-fragment, constrained never to straddle a shot cut**

Per-shot alone is too coarse: `sc_04` in the fixture is 305 characters over ~22.9s, which is several cues' worth of text no matter how it is styled. Per-fragment alone lets a cue survive a visual cut, which reads as a rendering bug rather than a stylistic choice.

The constraint costs little here: 19 shots over 58.3s averages ~3.1s per shot, so shots are already close to natural cue length. Split at shot boundaries first, then apply the character budget within each shot's span.

### 8.2 Style → **recommend white text, heavy black outline, no background box, raised off the bottom edge**

Outline rather than a box: a box occludes the image, and these are 9:16 videos where the picture is already cropped hard (the landscape-vs-vertical tension in the backlog). Outline stays legible over both bright and dark frames without hiding any of them.

**Raised off the bottom edge specifically** — TikTok, Reels and Shorts all overlay their own UI across roughly the bottom 12–15% of frame. Captions in a true lower third get covered by the caption/username/controls on every platform this targets. Sit them above that band.

Size should be set as a fraction of frame height, not in absolute points, so drafts and finals agree.

### 8.3 Karaoke-style word highlighting → **recommend NOT in v1**

It is the dominant look in this format and the character-level alignment makes it genuinely achievable, so this is worth doing eventually. Not first, for two reasons:

- It multiplies the ASS surface (per-word `\k` timing tags) and therefore the determinism surface, right where §5 says byte-identical output must be proven.
- You cannot evaluate whether the base cue timing is correct while simultaneously debugging highlight timing. Ship plain cues, confirm §3.1 is right against the fixture's ~8.8s drift signal, *then* add highlighting on a foundation known to be sound.

The alignment data is stored permanently, so nothing is lost by deferring.

### 8.4 Font → **recommend a single family covering both scripts, vendored — not a fallback stack**

libass font fallback is unreliable and platform-dependent, which is disqualifying under I5: "it picked a different font on that machine" is exactly the non-determinism §5 forbids. Do not plan on a stack.

**Noto Sans Devanagari is the recommendation**, because it ships Latin glyphs alongside Devanagari, so one family covers the mixed-script case with no fallback at all. Licence is SIL OFL — vendorable into the repo without issue.

Verify conjunct rendering (क्यों, स्थ) on real output before committing to it. And note §0: the current fixture cannot verify this, having 4 Devanagari characters in total.

### 8.5 `BURN_CAPTIONS` global or per-project → **recommend keeping it global config for now**

Whether to burn captions is a rendering setting, not a creative decision about *this video*, so config is the honest home and I2 is not implicated.

Two caveats. If it ever does become per-project it belongs on the Timeline as a decision field written through `append_version` (I3), never as a second config layer. And **either way it goes in the render fingerprint** (§6) — a project rendered with captions and one rendered without must never collide on a cache entry.

---

## 9. Effort

Roughly **2–3 days**, assuming the open decisions in §8 are made first:

- Cue derivation + segmentation, with tests: ~1 day. Most of the risk is here (§3.1).
- ASS serialisation + FFmpeg wiring + font vendoring: ~0.5 day.
- Fingerprint integration: a few hours, and non-negotiable (§6).
- Real-render verification, including looking at actual Devanagari output: ~0.5 day.

The estimate assumes captions render over the existing composition without needing changes to the filter graph's structure. If burning captions turns out to interact badly with the Ken Burns `zoompan` chain, add time — that would be discovered on the first real render, not before.

---

## 10. Verified corrections (2026-08-17)

Before any code was written, every technical claim above was checked against the real codebase and the real fixture project (§0 — now exported to `backend/tests/fixtures/captions_test_project.json`). Almost everything held exactly as written. Two things did not, and both change the cue-derivation design in ways worth recording here rather than only in commit history.

### 10.1 The "~8.8s drift" in §0 is the voice trap, not the transition-arithmetic bug

§0 attributes a ~8.8s gap ("67.1s of audio against a 58.329s video") to "18 transitions overlapping their adjacent shots," and §7 tells the reader to build the regression test around that number. Measured directly against the fixture's real alignment data:

| voice_id | summed narration duration |
|---|---|
| `0muxiGNHAVvmM1qWRtyV` (the timeline's actual active voice, `timeline.metadata.voice_id`) | **58.329s** — matches `total_duration_s` exactly, matches the real rendered `final.mp4`'s audio stream duration (58.328526s) to the millisecond |
| `T3s9anIvGvoeogXyFyMt` (a superseded voice-retry row) | 67.104s |
| `SLa3GDQHUGaRpH5GNvFL` (a superseded voice-retry row) | 55.634s |

The 67.1s figure is the **wrong voice's** total — a leftover from the N1 voice-retry residue §0 itself flags in its own last paragraph, not evidence of transition-overlap drift. For the *correct* voice there is no gap at all at the whole-timeline level. The real transition-overlap effect is smaller and separate: comparing `compute_shot_start_times` (correct, overlap-aware) against a naive additive sum of shot durations, drift grows monotonically to **4.7s** by the last scene (sc_06), not 8.8s, and is a genuinely different bug from voice selection. §7's regression test should be built around these verified numbers, not the original ~8.8s figure.

### 10.2 Caption timing must follow the audio-concat timeline, not `compute_shot_start_times`

§3.1 and §4.2 step 4 direct cue derivation to reuse `compute_shot_start_times` — "Do not infer this from the docs; read the render path and confirm against a real rendered file," which is exactly what turned up the correction. `app/renderer/audio.py::mux_narration` was read in full: it concatenates per-scene narration audio **back-to-back from t=0 via the ffmpeg concat filter, with zero knowledge of transitions or video-frame timing**. That is a *different* timeline from `compute_shot_start_times`, which *does* account for transition overlap.

Empirically, on this fixture, the two timelines agree at every scene boundary except one:

| scene starts | `compute_shot_start_times` (video-frame time) | cumulative narration duration (audio-concat time) |
|---|---|---|
| sc_02 | 7.059s | 7.059s |
| sc_03 | 17.879s | 17.879s |
| sc_04 | 22.848s | 22.848s |
| **sc_05** | **43.479s** | **43.979s** |
| sc_06 | 51.363s | 51.363s |

The one divergence (sc_04→sc_05, exactly 0.5s — one of the fixture's own transition durations) is a **cross-scene transition**: the last shot of sc_04 dissolves into the first shot of sc_05. `mux_narration` has no awareness this transition exists, so it doesn't subtract that 0.5s from the audio track the way `compute_shot_start_times` subtracts it from the video track. The two timelines quietly diverge by exactly the transition's duration from that point on, and would keep diverging further with every subsequent cross-scene transition in a longer timeline.

Since narration is the master clock (D1 — see `audio.py`'s own docstring: *"any sub-frame gap... is the video's rounding, not the audio's problem to absorb"*) and it's what the viewer actually hears, **captions must be timed against cumulative per-scene narration duration, not `compute_shot_start_times`.** Following §4.2 step 4 literally would produce captions synced to visual cuts but measurably desynced from the spoken words whenever a cross-scene transition exists — a subtler instance of exactly the failure class §3.1 warns about, introduced by the plan's own stated fix. This also simplifies implementation: no video-frame arithmetic is needed at all, only character-offset arithmetic (`Shot.narration_span`) plus each scene's own alignment array.

### 10.3 Other decisions locked during build

All of §8's open decisions were confirmed as written (per-shot-then-split granularity; white/outline/no-box/raised style; karaoke deferred to v2; Noto Sans Devanagari vendored — downloaded and verified: 551 mapped glyphs, Latin + Devanagari base and conjunct-forming characters present, `GSUB`/`GPOS` tables both present for real conjunct shaping, not just isolated glyphs; `BURN_CAPTIONS` stays global config). One additional operational finding: `backend/tests/conftest.py::clean_database` is autouse and function-scoped across all of `testpaths = tests`, so **any** `pytest` invocation — not just a full-suite run — truncates the shared dev Postgres, including a single test file under `tests/unit`. §0's warning undersells the blast radius; treat every `pytest` invocation as destructive, not just `pytest` with no path argument.

---

## 11. Implementation summary (2026-08-17)

Built end to end, per §1's design (cue derivation → ASS serialization → FFmpeg wiring → fingerprint integration), with the corrections in §10 applied rather than the original §3.1/§4.2 text.

**Shipped:**
- `backend/app/renderer/captions.py` — `derive_caption_cues` (per-shot segmentation on top of `split_narration_fragments`, timed against the audio-concat clock per §10.2), `serialize_ass` (white/heavy-outline/no-box/raised style per §8.2), `resolve_caption_font`/`caption_font_content_hash`, `escape_ffmpeg_filter_path`, `burn_captions` (the ffmpeg pass).
- `backend/app/workflow/steps/render.py` — new burn pass inserted between the silent render and narration mux (the one pass that must re-encode video); `_resolve_narration_audio` refactored into `_resolve_narration_rows` (full rows, reused for both audio muxing and cue derivation, so voice selection is resolved in exactly one place) plus a thin wrapper preserving the old signature for existing callers.
- `backend/app/renderer/fingerprint.py` / `RenderSettings` — `burn_captions`/`caption_font_hash`/`cue_list_hash` added following the R2 pattern exactly (required, unconditional, `None` when moot).
- `backend/vendor/fonts/NotoSansDevanagari-Regular.ttf` + `backend/vendor/OFL.txt` — vendored, not host fontconfig.
- `backend/app/core/config.py` / `.env` / `.env.example` — `caption_font` default changed from `Inter` to `Noto Sans Devanagari`.
- Tests: `tests/unit/renderer/test_captions.py` (21 tests — voice-selection trap, the sc_04→sc_05 clock correction, segmentation, determinism, ASS format, all against the real exported fixture except one deliberately synthetic shot-boundary case), `tests/unit/renderer/test_fingerprint.py` (3 new cases), `tests/integration/test_render_captions_determinism.py` (byte-identical-twice + smoke test, real ffmpeg).

**Verified, not just asserted:**
- Full suite run: 30 new tests + 269 existing unit + 18 render integration + 23 e2e/render-only, all passing, zero regressions.
- A real preview render (main fixture, real narration audio, real alignment) — audio/video durations matched to the millisecond, cue text and timing correct by eye and by direct script check.
- A real Devanagari preview render (`hinglish_final_project` fixture, already in the repo) — confirmed correct conjunct shaping (इस्तेमाल's स्त conjunct renders as one joined form, not tofu or a disconnected virama), not just glyph presence.
- One real bug caught only by testing against actual ffmpeg rather than trusting §4.3's one-line escaping example: `subtitles=C\:/path` alone is insufficient once `fontsdir=` is chained after it in the same `-vf` string. The working form needs `filename=`/`fontsdir=` explicit keys with each path additionally wrapped in single quotes — documented in `escape_ffmpeg_filter_path`'s own docstring.

**Not done, deliberately out of scope for this pass:** karaoke word-highlighting (§8.3, deferred to v2).
