# 14 — Burned Captions: Implementation Plan

> **Status:** plan only, nothing built. Written 2026-08-16.
> **Decision it implements:** [D2](13_Implementation_Guide.md) — captions come from script text plus TTS timings, never from transcribing our own narration audio.
> **Prerequisite already met:** [D1](13_Implementation_Guide.md) — ElevenLabs returns character-level alignment with the audio.

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

- **Cue derivation, unit** — against a real stored alignment fixture, not a synthetic one. The existing Hinglish project's narration rows are real character-level alignment over mixed script and are the right fixture.
- **The multi-scene offset case explicitly** (§3.1) — a two-scene timeline with a transition between them, asserting the second scene's first cue lands at the right second. This is the test that would catch the drift bug; without it, everything else passes and captions are still wrong.
- **Determinism** — same input, byte-identical ASS, twice.
- **Segmentation rules** — no cue exceeds the character budget, none is shorter than the minimum duration, cues tile without overlap.
- **Render smoke test** — one short real render with captions on, ffprobed, plus a visual check of a frame containing Devanagari to confirm §3.2 (this one genuinely needs eyes; no assertion catches tofu).

---

## 8. Open decisions — needed before building

1. **Cue granularity** — one cue per shot, or per readable fragment independent of shot boundaries? Per-shot is simpler and guarantees captions never straddle a cut; per-fragment reads better when a shot is long. Recommend per-fragment with a shot-boundary constraint, but this is a creative call.
2. **Style** — position, size, outline/shadow, background box. Vertical short-form convention is large, high-contrast, lower third but above the platform UI overlay. Currently unspecified beyond a font name.
3. **Karaoke-style word highlighting?** Character alignment makes it possible. It is also the dominant look in this format. Materially more work in ASS, and a scope question, not a technical one.
4. **Which font**, and vendored under what licence (§3.2).
5. **Is `BURN_CAPTIONS` per-project or global?** Currently global config. A per-project override on the Timeline would be an I2 decision field, not config — worth settling before it is assumed either way.

---

## 9. Effort

Roughly **2–3 days**, assuming the open decisions in §8 are made first:

- Cue derivation + segmentation, with tests: ~1 day. Most of the risk is here (§3.1).
- ASS serialisation + FFmpeg wiring + font vendoring: ~0.5 day.
- Fingerprint integration: a few hours, and non-negotiable (§6).
- Real-render verification, including looking at actual Devanagari output: ~0.5 day.

The estimate assumes captions render over the existing composition without needing changes to the filter graph's structure. If burning captions turns out to interact badly with the Ken Burns `zoompan` chain, add time — that would be discovered on the first real render, not before.
