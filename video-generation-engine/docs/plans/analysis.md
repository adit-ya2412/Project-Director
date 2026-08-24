# SFX (Whoosh) + Background Music — Diagnosis & Change Plan

I traced both pipelines end-to-end in the code and **queried your actual three projects in the DB**. Two smoking guns found. Everything below cites real files/lines.

---

## Part A — How SFX works today (the full path)

### A1. Where the whoosh is *picked*

**`backend/app/workflow/steps/select_sfx.py`** — `SelectSfxStep` runs early in the pipeline (after music selection, **before** narration — its position is load-bearing: it appends a `produced_by=SFX_SELECTION` version, and narration must remain the last pre-approval appender or every render goes silent).

```python
_DEFAULT_QUERIES = {
    SfxKind.WHOOSH.value: ["whoosh", "swoosh cinematic"],
    SfxKind.STINGER.value: ["stinger", "cinematic impact"],
    SfxKind.TRANSITION.value: ["swoosh transition", "whoosh"],
}
```

For each kind it calls `provider.search(...)` → licence gate (`cc0/by`) → `rank_sfx_candidates(...)` → fetches **exactly ONE clip** → writes it to disk → records provenance.

**Provider**: `settings.sfx_provider = "local"` → **`backend/app/providers/local_sfx.py`** reads `backend/storage/sfx_library/manifest.json` (10 clips on disk: 3 whoosh, 4 stinger, 3 transition).

**Ranking**: `backend/app/assets/sfx_ranking.py` — clips that fit `settings.sfx_max_clip_s` **intact** rank first, then shorter-is-better, then term-overlap, then alphabetical `source_id`:

```python
return (
    0 if fits else 1,
    over,
    -sfx_candidate_relevance(query_terms, candidate),
    candidate.source_id,   # ← deterministic tiebreak, same for every project
)
```

### A2. Where it's *stored* ("project memory")

Two places, by design (I2 — decisions in the Timeline, bytes on disk):

| What | Where |
|---|---|
| The audio bytes | `storage/{project_id}/sfx/{content_hash}.mp3` |
| The **decision** (provenance: kind, provider, track_id, licence, attribution, content_hash) | `Timeline.sfx_plan.clips` — JSONB in `timeline_version.document`, written via `append_version(produced_by=SFX_SELECTION, owns={"sfx_plan"})` (`backend/app/schemas/timeline.py`: `SfxPlan` / `SfxClipSelection`) |

There is **no SFX database table** — deliberate. `sfx_plan.selection_attempted` makes "tried, found nothing" a resumable state.

### A3. Where it's *used* (render)

**`backend/app/workflow/steps/render.py` → `_sfx_overlays()`**: `by_kind = {clip.kind: clip for clip in timeline.sfx_plan.clips}` (one clip per kind), then **`backend/app/renderer/sfx.py` → `derive_sfx_events()`**:

```python
if shot.camera.movement == CameraMovement.PUNCH_IN:
    offsets = punch_in_frame_offsets(shot.camera, frames=frames)  # 2 punches/shot
    events.extend(SfxEvent(kind=SfxKind.WHOOSH, offset_s=start_s + frame / fps) ...)
```

→ **`mux_sfx()`**: one `-i` input **per event**, each chained `atrim=0:{max_clip_s}` → `afade` → `volume={gain}` → `adelay={ms}` → `amix` onto the narration+music mix.

### A4. Why the whoosh is bad — measured, not guessed

From your DB (all three projects, active timeline):

| Project | Style | Punch-in shots | Whoosh events | Clip chosen |
|---|---|---|---|---|
| Oil and War | retention_fast | 53/54 | **~106** | `swosh_swoosh_whoosh_air_sound...mp3` |
| Beauty and Disease | retention_fast | 29/29 | ~58 | same clip |
| Radar and worlwar2 | retention_fast | 44/46 | ~88 | same clip |

1. **The same 0.49s air-swish plays ~100 times per video.** No rotation, no variety — one clip per kind, deterministic, identical across every project.
2. **The clip itself is the weakest whoosh in the library.** I measured loudness with ffmpeg: `swosh_swoosh` peaks at **−7.3 dB** (soft swish); `deep_whoosh_1` — a real cinematic whoosh — peaks at **−1.9 dB** but is 3.16s and **excluded** by your hand-lowered cap.
3. **Your uncommitted config tweaks** (`git diff backend/app/core/config.py`: `sfx_gain_db` −8→−13, `sfx_max_clip_s` 1.5→0.8) tried to tame it — but 0.8s also **re-broke R15's curation**: the timpani stinger (1.242s) gets trimmed mid-hit again, and with −13 dB the whoosh is now buried (peak ≈ −20 dB).
4. **`atrim=0:{max}` trims from the START** — a long whoosh's impact transient is at its *end*, so even a trimmed `deep_whoosh` would keep only the quiet build-up.
5. Leftover debug: `print("gain_linear", ...)` at `backend/app/renderer/sfx.py:100`.
6. **Latent crash risk**: one `-i` per event → your "Oil and War" render built a ~29KB ffmpeg command — ~10% under Windows' 32,767-char `CreateProcess` limit. A long-form punch-in video (370+ events) **will crash on Windows**.

---

## Part B — How background music works today

### B1. The path

1. **Brief**: the Director writes `music_plan` (mood, tempo, `search_terms`).
2. **`backend/app/workflow/steps/select_music.py`** — `SelectMusicStep`, before the approval gate (search is free → A5).
3. **Provider**: chosen by `settings.music_provider` — config default is `"local"` (the curated 54-track library, `backend/app/providers/local_music.py`). **Verified against the current working tree (not just assumed)**: `.env:153` (`MUSIC_PROVIDER=openverse`) is already **commented out**, so a fresh process boot now resolves `music_provider` to `"local"`. The override is therefore **not currently live in this checkout** — it is a **historical** cause for the three DB rows below, either predating the line being commented, or a still-running process/container that read the old `.env` before the comment was added and never restarted. Before touching anything else, **Act must first confirm the running service's actual env** (`docker-compose config`, or `docker exec <container> env | grep MUSIC_PROVIDER`) rather than assume the file on disk is what the live process sees.
4. **Ranking**: `backend/app/assets/music_ranking.py` — lexicographic: duration floor → term-overlap relevance → tempo band → **plain `source_id` tiebreak**.
5. **Storage**: bytes → `storage/{project}/music/{content_hash}.mp3`; selection provenance → `Timeline.music_plan.selected_track` (`MusicTrackSelection`) via `append_version(produced_by=MUSIC_SELECTION)`. Per-act beds (`act_beds`) for long-form.
6. **Render**: `render.py` → `_music_segments()` → `mux_music()` (loop+trim, duck under narration, per-style gains via `resolve_music_gains`).
7. **Existing human control**: only `POST /{id}/music/retry` (reset + optional new search terms) — **no upload path**.

### B2. Why all three projects got the same BGM — confirmed in the DB

```
Oil and War        | openverse | 057198c0-... | "Documentary Music Strings" by tyops (CC BY 4.0)
Beauty and Disease | openverse | 057198c0-... | "Documentary Music Strings" by tyops
Radar and worlwar2 | openverse | 057198c0-... | "Documentary Music Strings" by tyops
```

Two compounding causes:

1. **A (likely historical, must be re-confirmed) `.env`/runtime override to Openverse** — the curated 54-track local library that was built specifically to replace Openverse was not being used at the time these three rows were produced. The `.env` file in the current checkout already has this line commented out (see B1 note above), so this cause may already be resolved; Act's first job is to confirm the *running* service's actual env, not to "fix" a line that may no longer need fixing.
2. **No per-project variety exists anywhere — this is the real, still-live root cause regardless of provider.** Ranking is fully deterministic *across projects*. That track's title literally contains "Documentary Music Strings" — it wins term-overlap outright for every documentary-ish brief, on **either** provider (Openverse or the local library), because `rank_music_candidates`'s tiebreak is a plain `source_id` sort with no project-specific input at all. Notably, the plan's own decision **M10** ("pick deterministically from the *project seed*") was designed but **never implemented** — image generation has `_project_seed` (`resolve_assets.py:244`); music has nothing. **This makes the seeded tiebreak (C2 below) the mandatory fix; the `.env` line is a should-verify, not the load-bearing one.**

---

## Part C — Proposed changes

### C1. **Upload your own BGM** (the main ask) — `POST /projects/{id}/music/upload`

Following the exact precedents already in the codebase (`upload_assets` for images at `api/projects.py:790`, `retry_music_selection` at `:1878`, `_resume_after_human_correction` at `:312`):

1. **New `validate_and_identify_audio(content)`** in `backend/app/assets/validation.py` — ffprobe-based mirror of `validate_and_identify_video`: positively confirm a real **audio stream** with positive duration, enforce `max_download_bytes`, return the detected extension (mp3/wav/m4a/ogg/flac). Rejects anything undecodable *at the endpoint*, not inside ffmpeg (A27 discipline).
2. **Storage**: `storage/{project}/music/{content_hash}.{ext}` — note `_music_file()` in `render.py:599` currently builds a hardcoded `f"{content_hash}.mp3"` path and raises `PermanentError` if it's missing; it must change to a glob lookup (`next(iter((storage_root/project_id/"music").glob(f"{content_hash}.*")), None)`, still raising `PermanentError` when nothing matches) so an uploaded `.wav`/`.m4a`/`.ogg`/`.flac` resolves correctly. Apply the identical fix to `_sfx_overlays` in the same file (`render.py:664`, currently hardcodes `.mp3` too) if SFX upload (C3f) ships in the same pass — both call sites share this bug. Re-downloaded provider `.mp3`s are unaffected either way since their extension is always `.mp3`.
3. **Timeline record** via `append_version(produced_by=HUMAN, owns={"music_plan"})`:
   ```python
   base.music_plan.selected_track = MusicTrackSelection(
       provider="project_music", track_id=<hash.ext>, source_url="",
       licence="user_supplied",
       attribution="Supplied by the project owner" (or original filename),
       content_hash=content_hash)
   base.music_plan.selection_attempted = True
   base.music_plan.act_beds = []   # single bed for the whole video (open decision below)
   ```
   Licence gate bypassed — a human's own file is judged by the human (A24 precedent).
4. **Resume** through `_resume_after_human_correction` (identical tail to music-retry: re-approve if already approved, background the engine) → re-render is automatic and the render **fingerprint already changes** via `music_content_hash_for(timeline)` — no stale-cache risk (R2 discipline already satisfied here).
5. **Frontend**: the "Music attribution" card in `frontend/src/pages/Result.tsx` (line ~250) gains an *Upload your own* control; `api.ts` gets `uploadMusic()` using the existing FormData pattern (`uploadAssets` at `api.ts:141`); a `useUploadMusic` mutation in `queries.ts`.
6. **Tests**: new `tests/e2e/test_music_upload_api.py` mirroring `test_music_retry_api.py` + `test_upload_and_override_api.py` (invalid bytes → 400; upload → `selected_track.provider == "project_music"` → re-render muxes the real file; upload before approval doesn't self-approve).

### C1a. Why a naive upload endpoint would fail — traced against the real render code

`mux_music`/`build_ducked_bed` (`backend/app/renderer/music.py`) are content-agnostic — the ducking envelope is pure gain math over timestamps, so it works on *any* audio file. The failures are all in assumptions the pipeline makes about "a music track" that the curated 54-track library quietly satisfies and an arbitrary upload won't. Five concrete scenarios, traced against the current code:

1. **Wrong extension → hard crash.** `_music_file()` (`render.py:599-600`) hardcodes the lookup as `f"{content_hash}.mp3"`. A `.wav`/`.m4a`/`.ogg` upload (very likely — most people don't have a stray `.mp3`) gets stored under its real extension but the render step looks for a `.mp3` that doesn't exist → `PermanentError("...audio file is missing on disk")`. Render fails outright. Already flagged in C1 item 2 above — the glob-lookup fix is mandatory, not optional, the moment upload ships.
2. **Short track → audible loop seam.** `mux_music` reads the file with `-stream_loop -1` then `atrim`s to the video's real length (`music.py:195-200`). There's no crossfade at the loop boundary. A 20s jingle looped under a 90s reel hard-restarts every 20s with an audible click/jump unless the source file happens to loop seamlessly (most music doesn't).
3. **Long track → arbitrary, unmusical cutoff.** The same `atrim` just takes the file's first N seconds and hard-cuts there; only the last `_FADE_SECONDS` (1.0s) gets a fade. A 3:45 song under a 90s reel plays whatever the first 90 seconds happens to be (often a slow intro, no hook) and stops mid-phrase.
4. **Loudness mismatch.** `music_bed_gain_db` (e.g. −10 dB for `retention_fast`) was tuned by ear against the curated library's roughly-consistent mastering. A random upload can be mastered anywhere from −6 to −20 LUFS — the same fixed gain either buries narration or is inaudible. There is no per-track loudness normalization for music anywhere in the pipeline (SFX has this *proposed*, C3c — music doesn't even have that).
5. **Long-form/act projects: the upload can be silently ignored.** `_music_segments()` (`render.py:627-643`): when `timeline.music_plan.act_beds` already has 2+ selected tracks, that branch wins and `selected_track` is never even read. If the upload endpoint (as sketched in C1) only writes `music_plan.selected_track` without explicitly clearing `act_beds`, the upload succeeds, shows in the UI, re-renders without error — and the render keeps playing the old auto-picked per-act beds. No error, no log, just the wrong audio. This is the one that would ship silently broken rather than crash loudly.

None of these are reasons not to build it — they're the difference between "upload endpoint" and "safe upload endpoint." At minimum, C1 needs: the glob-lookup fix (already listed), an explicit `act_beds = []` on upload, a duration floor + rejection message for too-short files (simplest fix for #2 — a real crossfade-loop is more DSP work than v1 needs), and either a measured per-track compensating gain (mirrors C3c) or an explicit user-facing volume control for #4. #3 (which slice of a long track to use) can ship as "trims from the start, tell the user to pre-trim" for v1; a `start_offset_s` field is a small addition if wanted later.

### C2. Fix "same BGM every project"

1. **Verify, then decide, `.env`/runtime provider config** — **corrected**: `.env:153`'s `MUSIC_PROVIDER=openverse` line is *already commented out* in the current checkout (config default is `music_provider="local"`, `config.py:146`). Act's actual step 1 here is to confirm the deployed/running service resolves to `"local"` (check the live container's env, not just the repo file) and only then decide deliberately whether to keep Openverse registered-but-unused or remove it entirely — there is no line left to "delete" in the file as it stands.
2. **Implement M10's project-seeded pick (the mandatory fix, applies regardless of provider)** in `SelectMusicStep._select`: among candidates that tie on the `(duration_floor, relevance, tempo_band)` key — or the top-K within a small relevance epsilon — pick by `hashlib.sha256(f"{project_id}:{source_id}")` instead of plain `source_id`. Same project → same track (I5 holds); different projects with the same brief → different tracks. `rank_music_candidates` stays pure; the seeding happens at the call site where the project id is in scope.
3. *(Optional, larger)* a `GET /{id}/music/candidates` endpoint + picker UI so you can browse the library per project. Deferred unless you want it.

### C3. Fix the whoosh

- **C3a — Rotation (variety)**: `SelectSfxStep` selects **up to 3 clips per kind** (all validated fits), not 1. Renderer's `_sfx_overlays` changes `by_kind` to `dict[SfxKind, list[...]]` and rotates deterministically by event index (events are already sorted — I5 safe). Same clip never plays twice in a row.
- **C3b — Placement restraint**: a minimum gap between whoosh events (config `sfx_min_gap_s`, ~1.0–1.5s) or first-punch-only per shot — deterministic; **must enter `compute_render_fingerprint`** (the §7 lesson, 6th occurrence — `sfx_max_clip_s` already does, the new knob must too).
- **C3c — Loudness normalization instead of one global gain**: measure each clip's peak (volumedetect at selection time, or store it in the SFX manifest) and compute a per-clip `volume` so every clip hits a target peak (~−12 dBFS). Your three whooshes span −0.2 to −7.3 dB — a single `sfx_gain_db` can't serve them all. Per-kind gain overrides (`sfx_whoosh_gain_db`, …) fingerprinted.
- **C3d — End-aligned trim**: when a clip exceeds `sfx_max_clip_s`, trim `atrim=start={dur−max}` (keep the impact transient) instead of `atrim=0:{max}` (which keeps only the quiet build-up). Makes the good 3.16s `deep_whoosh` usable. **Needs a source for `dur` that doesn't exist yet**: `mux_sfx` currently only receives `max_clip_s`, never the clip's own duration. Two options — (a) store `duration_s` per clip in `manifest.json` (already has it for the local library per A1/A2, so read it through at selection time in `select_sfx.py` and carry it into `SfxClipSelection` or a sibling lookup) and pass it through to `mux_sfx`'s overlay tuples; or (b) probe each overlay file with `probe_duration_seconds` inside `mux_sfx` itself before building the filter graph (extra ffprobe call per unique clip, not per event, if C3h's dedupe lands first). Pick (a) for a project-uploaded SFX override (C3f) since manifest lookup doesn't apply there — `validate_and_identify_audio` should return duration so it can be threaded through the same way music duration already is.
- **C3e — Curate better whooshes**: extend `backend/scripts/download_sfx_library.py` (it already has `--fill-short`) to fetch 2–3 punchy 0.6–1.2s whooshes ("cinematic whoosh", "impact whoosh short") and update `manifest.json` — then **restore `sfx_max_clip_s` to 1.5** (or a per-kind ceiling) so curated clips fit intact again.
- **C3f — Human control (parity with music/shots/narration)**: `POST /projects/{id}/sfx/{kind}/override` — multipart optional file (validated+hashed → `storage/{project}/sfx/{hash}.mp3`, replaces that kind's clip in `sfx_plan.clips` via `append_version(produced_by=HUMAN, owns={"sfx_plan"})`) and an `enabled=false` form flag that removes the kind's clip entirely (the renderer already skips kinds with no clip → that *is* disable). Plus optionally `POST /sfx/retry` (reset, mirror of music retry). Upload changes `sfx_content_hashes` → fingerprint changes → correct re-render.
- **C3g — Cleanup**: delete the `print("gain_linear", ...)` debug line (`backend/app/renderer/sfx.py:100`, confirmed present and still uncommitted in the working tree). Also resolve the **currently-uncommitted working-tree diff** on `sfx_gain_db`/`sfx_max_clip_s` (`backend/app/core/config.py:181-182`): HEAD/committed values are `sfx_gain_db=-8.0`, `sfx_max_clip_s=1.5`; the working tree has them changed, uncommitted, to `-13.0`/`0.8` (the latter is what excludes the good `deep_whoosh_1` clip per A4). Act must make one deliberate choice, not leave the diff dangling: either (i) revert both to committed `-8.0`/`1.5` outright, or (ii) keep `-13.0` (quieter gain, defensible on its own) but raise `sfx_max_clip_s` back above `1.5` (or to a per-kind ceiling per C3e) so the trim exclusion is undone either way — the working combination of `-13.0`/`0.8` must not survive this pass since it is the direct, measured cause of the weak-clip selection in A4.
- **C3h — Hardening (medium effort, not trivial)**: dedupe `mux_sfx` inputs — one `-i` per **unique clip** (3 total, or more once C3a's up-to-3-per-kind rotation lands) + `asplit=N` branches feeding each event's own `adelay`, instead of one `-i` per event. This is more than a mechanical shrink of the existing filter graph: today each event gets its own `[{index}:a]atrim...volume...adelay[label]` chain built directly off its own ffmpeg input index (`sfx.py` around line 130); after dedupe, multiple events sharing a clip must all branch off the *same* `asplit` output, so the per-event label wiring and the `amix` input count both need rebuilding, not just fewer `-i` flags. Eliminates the Windows argv-length crash risk at long-form scale (A4's ~106-event case) and shrinks the filter graph roughly in proportion to events-per-unique-clip, not a fixed ~30×.

---

## Part D — Working-tree and storage state, verified 2026-08-24

Re-checked on disk before the decisions below were taken, because several of them depend on it.

### D1. The uncommitted config diff is still live

`git diff backend/app/core/config.py backend/app/renderer/sfx.py` confirms both A4 items are unchanged and unreverted:

- `sfx_gain_db` **−8.0 → −13.0**, `sfx_max_clip_s` **1.5 → 0.8** (`config.py:181-182`)
- `print("gain_linear", gain_linear)` still at `sfx.py:100`

### D2. The hand-fix is NOT in the working tree — the SFX library has been restored

**`backend/storage/sfx_library/` is fully intact and git-clean.** All 10 clips are tracked, present on disk, and match HEAD; `manifest.json` is unmodified and still lists all three whooshes. The deletion is visible only in its *effects*, in per-project storage:

| | |
|---|---|
| Projects with an `sfx/` dir | 9 |
| With **stinger + transition only, no whoosh** | 8 |
| With a whoosh clip | 1 (`f9dd2599-…`, holding `2c634c18…` = `swosh_swoosh…mp3` — the exact clip named in A4) |

Confirmed by hashing the library files and matching them against the per-project content-hash filenames:
`462f5ec2…` = `stinger/timpani_sting.mp3` (all 9 projects) · `260384a6…` = `transition/swoosh_15_windy.mp3` (7) · `c22face7…` = `transition/space_swoosh_brighter.mp3` (2) · `2c634c18…` = `whoosh/swosh_swoosh…mp3` (1).

⚠ **Consequence: the next project rendered will select a whoosh again.** With `sfx_max_clip_s=0.8`, both `swipe_whoosh` (0.448s) and `swosh_swoosh` (0.49s) fit, so `over` is `0.0` for both and length does **not** break the tie — relevance does, and `swosh_swoosh`'s title carries both "swoosh" and "whoosh". Same weak clip as A4. The hand-fix protected the already-rendered projects; it protects nothing going forward.

**Correction to A1's description of ranking**: A1 says the key is "fits → shorter-is-better → term-overlap → source_id". Reading `rank_sfx_candidates` (`sfx_ranking.py:31-39`), `over` is `0.0` for *every* fitting clip, so shorter-is-better applies **only among clips that do not fit**. Among fitting candidates the order is relevance, then `source_id`. This is why the 0.49s clip beats the 0.448s one.

### D3. On `retention_fast`, whoosh is the only SFX you actually hear

`derive_sfx_events` (`sfx.py:71-74`) emits a `TRANSITION` event only when `transition.type != CUT and transition.duration_s > 0`. `retention_fast` is cuts-only by its own prompt fragment, so **transition events never fire on it** — the transition clip sitting in those project folders was downloaded by `SelectSfxStep` (which fetches one clip per kind unconditionally) but never played. `STINGER` fires only on shots carrying a `text_card`. So on a fastcut reel the audible SFX layer is whoosh, and whoosh alone.

---

## Open decisions — RESOLVED 2026-08-24

All seven resolved scenario by scenario, plus three follow-ups the answers forced. Recorded with reasoning so nobody re-opens them blind.

| # | Decision | Resolution |
|---|---|---|
| 1 | Music provider going forward | **Keep Openverse registered but unused** — leave the `.env` line commented out. `"local"` stays the code default. No code change; C2's only job here is confirming the *running* service resolves to `"local"` (`docker exec … env \| grep MUSIC_PROVIDER`). The keep-or-delete-entirely question is deliberately parked, not answered. |
| 2 | BGM upload on a long-form/act project | **One bed for the whole video.** Upload sets `music_plan.act_beds = []` explicitly, so `_music_segments()`'s `len(beds) >= 2` branch cannot silently win over `selected_track` (C1a #5). Act boundaries ignored for uploaded music. |
| 3 | Whoosh restraint | **Both** — first-punch-only per shot, then drop anything still within `sfx_min_gap_s` (~1.5s) of the previous kept event. ~40-45 events instead of ~106 on a 54-shot reel. ⚠ Superseded in *priority* by decision 5 — see "What this means for C3". |
| 4 | SFX control surface | **Upload + per-kind disable** (C3f as written). No clip-picker UI. `enabled=false` removes the kind's clip; the renderer already skips kinds with no clip, so disable costs nothing. The non-destructive, per-project version of what was done by hand in D2. |
| 5 | Replace vs re-tune whoosh clips | **Neither — whoosh off by default**, revisited later. Codifies the hand-fix properly instead of curating or tuning clips that would then sit unused. |
| 6a | Short BGM uploads | **Accept any length, warn in the UI.** No duration floor. If the track is shorter than the video, the response carries a warning the Result page shows ("will loop N times, seams may be audible"). No crossfade-looping work in v1. |
| 6b | Long BGM uploads | **Use the first N seconds, warn in the UI** ("using the first 1:35 of your 3:48 track — pre-trim the file to choose a different section"). No `start_offset_s` field, no scrubber. Current `atrim` behaviour, made explicit. |
| 7 | BGM loudness | **Gain slider now, normalization later.** Ship a dB offset control next to the upload (default 0) in v1; add a `loudnorm` measurement pass as a follow-up that sets the slider's *default* rather than replacing it. Neither pass is wasted work. The slider value **enters `compute_render_fingerprint`**. |

### Follow-ups forced by decision 5

| # | Question | Resolution |
|---|---|---|
| 5a | "Off by default" — which styles? | **`retention_fast` only.** A per-style field on `StylePacingBand`, resolved with `is not None`, exactly like `narration_speed` (R8) and `music_bed_gain_db` (leftover item 5). `documentary_archival` and `stillness` keep whoosh on their occasional punch-in shots, where the density problem does not exist. |
| 5b | How much of the C3 quality pass still ships? | **C3c + C3d only.** Both are non-whoosh-specific and land on the stinger, which still fires on every text card. C3a (rotation) and C3b (restraint) are **deferred** until whoosh is actually turned back on for a project. |
| 5c | The dangling `sfx_gain_db`/`sfx_max_clip_s` diff (C3g) | **Revert both to committed `−8.0` / `1.5`.** `1.5` restores R15's curation — stinger (1.242s) and transition (1.013s) fit intact again — and `−8.0` becomes C3c's normalization target. The `−13`/`0.8` pair existed solely to tame the whoosh; with whoosh off on the style that needed taming, its justification is gone. |

⚠ **Three earlier inline answers in this file were superseded on confirmation** and are recorded here so the older text isn't mistaken for the decision: a **30-second** whoosh min-gap (would have left ~3 events on a 95s reel — near-silence rather than restraint; resolved to ~1.5s as part of "both"), **reject-short-uploads** (resolved to accept-and-warn), and **slider instead of normalization** (resolved to slider *first*, normalization as a follow-up).

### What this means for C3

The shape of the SFX work changed substantially:

- **C3a (rotation) and C3b (restraint) are deferred.** Decision 3 still stands as the *policy* for whoosh whenever it is enabled — it is not reversed — but it now serves a path that is off by default on the only style with the density problem. Build it when whoosh comes back, not before.
- **A4.6's Windows argv crash risk largely evaporates.** Whoosh generated essentially all the event volume on a fastcut reel (D3). With it off on `retention_fast`, C3h drops from "latent crash at long-form scale" to genuine hardening that can wait.
- **C3e (curation) is deferred alongside C3a/C3b.** No ear-time spent auditioning whoosh candidates for a path that is off.
- **The stinger becomes the main beneficiary of this pass** — 5c's cap revert stops it being cut mid-hit, C3c normalizes its level, C3d preserves its transient if it ever exceeds the cap.

### Still open (deliberately)

- Whether to remove Openverse from the codebase entirely (decision 1 parked it, did not answer it).
- When, and on what evidence, whoosh gets turned back on for `retention_fast` — decision 5 is "revisit later" with no trigger defined.
- Crossfade looping (6a) and `start_offset_s` (6b) remain the named stretch items if warn-only proves annoying in practice.
- The `loudnorm` measurement pass behind decision 7's slider.

## Sequencing — revised against the resolved decisions

1. **C3g cleanup** — delete the debug print, revert `sfx_gain_db`/`sfx_max_clip_s` to `−8.0`/`1.5` (decision 5c). One line plus one config revert; do it first so nothing downstream is tuned against the dangling values.
2. **Whoosh off for `retention_fast`** (decisions 5 + 5a) — a per-style field on `StylePacingBand`, the same shape as `narration_speed`. This is the smallest change that actually fixes the reported symptom, and it makes the restored library (D2) safe again.
3. **C1 BGM upload** (the ask) — built per C1a with decisions 2, 6a, 6b, 7: glob lookup, explicit `act_beds = []`, warn-don't-reject on short/long tracks, gain slider.
4. **C2** — runtime provider verification (decision 1) + the seeded tiebreak, which is the still-live root cause of every project getting the same track.
5. **C3f** — SFX upload/disable per kind (decision 4). Shares most of its validation and storage code with C1, so it is cheaper after C1 than before it.
6. **C3c + C3d** (decision 5b) — loudness normalization and end-aligned trim, aimed at the stinger.
7. **Deferred until whoosh is re-enabled**: C3a rotation, C3b restraint (policy already decided — first-punch + ~1.5s gap), C3e curation.
8. **Deferred, low urgency**: C3h dedupe hardening — the crash risk it addresses largely disappears once whoosh is off on fastcut.

## Effort estimate: C1 (BGM upload), built safely per C1a

Sized against comparable, already-shipped work in this codebase (image `upload_assets`, `retry_music_selection`, R8/R11's speed work) — not a guess from zero.

| Piece | Work | Size |
|---|---|---|
| `_music_file()` glob-lookup fix (C1 item 2) + same fix on `_sfx_overlays` | One function each, existing pattern | ~1 hr |
| `validate_and_identify_audio()` | ffprobe mirror of `validate_and_identify_video` — exact existing precedent | ~2-3 hrs |
| `POST /music/upload` endpoint + `append_version` write, **including explicit `act_beds = []`** (C1a #5) | Follows `retry_music_selection`/`upload_assets` shape closely | ~half a day |
| Short/long-track warnings surfaced to the UI (decisions 6a, 6b) — compare upload duration to video duration, return a warning string | No rejection logic; one comparison plus a message | ~1-2 hrs |
| Gain slider (decision 7) — dB offset on the selection, threaded into `mux_music` **and** `compute_render_fingerprint` | Mirrors how `resolve_music_gains` already passes one resolved pair to both (R2) | ~2-3 hrs |
| Frontend: upload control + gain slider on the Result page + `uploadMusic()` + mutation hook | Existing FormData/mutation patterns to copy | ~half a day |
| Tests (upload API, extension-variety, `act_beds` clearing, warning thresholds, fingerprint regression) — **cannot run e2e yet, see note below** | Mirrors `test_music_retry_api.py` | ~half a day |
| **Total, v1 as decided** | | **~2-2.5 days** |
| *Follow-up*: `loudnorm` measurement setting the slider's default (decision 7's second half) | New, no direct precedent | ~1 day |
| *Stretch, if wanted*: `start_offset_s` picker, real crossfade looping | Genuinely new DSP-ish work | +1-2 days |

Decisions 6a/6b/7 took roughly a day off the earlier estimate by choosing warn-over-reject and slider-over-normalization. The endpoint plumbing (storage, timeline write, resume, re-render) is small — it's C1a's five failure modes, not the upload mechanics, that set the floor. #1 (glob lookup) and #5 (`act_beds`) are the two that are **not** optional: skipping #1 crashes the render, skipping #5 ships something that looks done and silently plays the wrong audio.

**Add, outside C1**: C3g cleanup + the `retention_fast` whoosh-off flag (sequencing steps 1-2) are ~**half a day** together, and they are what actually fixes the symptom you reported. Worth doing before C1, not after.

**⚠ TEST-DB HAZARD — corrected 2026-08-24 per review RV3 (the original wording of this paragraph understated the risk).** The hazard is **not** limited to the e2e suite: `backend/tests/conftest.py` carries an AUTOUSE `clean_database` fixture that TRUNCATEs every table in the real Postgres **before every test** — a bare `pytest tests/unit/...` destroys all 7 real projects exactly as surely as the full e2e suite would. As of 2026-08-24 this is gated: truncation now requires `PYTEST_TRUNCATE_DB=1` (unset = the fixture yields without touching the database; `make test` sets it, so the documented "one full-suite run, alone, in the foreground" workflow is unchanged). Until fixtures are exported or a separate test DB exists: run unit tests freely (they pass with zero DB contact), set the env var ONLY against a disposable database, and do manual verification of "does it sound right" against the 7 real projects.

## Testing & conventions (per this codebase's rules)

- Every new render input **enters `compute_render_fingerprint`** with a regression test — the R2 lesson, now hit six times. Per the resolved decisions that means: the **BGM gain slider** (decision 7), the **per-style whoosh-enabled flag** (5a), the **normalization target** (C3c), and later `sfx_min_gap_s` (3) and the rotation policy (C3a) when whoosh is re-enabled.
- All corrections via `append_version` (I3), provenance-only in the Timeline (I2), determinism everywhere (I5: sorted events, no set iteration, seeded picks).
- Unit tests for pure functions; integration tests with real ffmpeg (isolated volume measurements like the ducking proof); e2e over the real HTTP surface on DRY_RUN fakes; `ruff`/`black`/`mypy` from the repo root; **one full-suite run, alone, in the foreground** — your three real projects live in the shared Postgres, so export fixtures first.

---

## Implementation progress — per-flow review log

Status per the revised sequencing above. Each completed task gets a dated
entry here describing exactly what changed, how it was verified, and what
to check when reviewing. Review comments should reference these entries.

| # | Flow | Status | Entry |
|---|---|---|---|
| 1 | C3g cleanup (debug print + config revert) | ✅ **DONE — awaiting review** | [P1](#p1--c3g-cleanup-2026-08-24) |
| 2 | Whoosh off for `retention_fast` (decisions 5 + 5a) | ✅ **DONE — awaiting review** | [P2](#p2--whoosh-off-for-retention_fast-2026-08-24) |
| 2a | Review fixes RV1–RV4 (probe kwarg, drift invariant, conftest gate) | ✅ **DONE — awaiting review** | [P2a](#p2a--review-fixes-rv1rv4-2026-08-24) |
| 3 | C1 BGM upload (glob fix, `act_beds=[]`, warn-don't-reject, gain slider) | ✅ **DONE — awaiting review** | [P3](#p3--c1-bgm-upload-2026-08-24) |
| 4 | C2 provider verification + project-seeded tiebreak | ✅ **DONE — awaiting review** | [P4](#p4--c2-provider-verification--seeded-tiebreak-2026-08-24) |
| 5 | C3f SFX upload/disable per kind | ✅ **DONE — awaiting review** | [P5](#p5--c3f-sfx-uploaddisable-per-kind-2026-08-24) |
| 5a | Review fixes RV7–RV10 | ✅ **DONE — awaiting review** | [P5a](#p5a--review-fixes-rv7rv10-2026-08-24) |
| 6 | C3c + C3d loudness normalization + end-aligned trim | ✅ **DONE — awaiting review** | [P6](#p6--c3c-c3d-normalization--end-aligned-trim-2026-08-24) |
| 7 | C3a/C3b/C3e rotation, restraint, curation | ⏸ deferred until whoosh re-enabled | — |
| 8 | C3h mux dedupe hardening | ⏸ deferred, low urgency | — |

### P1 — C3g cleanup (2026-08-24)

**Scope executed:** sequencing step 1 only — decision 5c applied verbatim,
nothing else touched.

**Changes:**

1. `backend/app/renderer/sfx.py` — deleted the leftover debug line
   `print("gain_linear", gain_linear)` (was at line 100). The legitimate
   `gain_linear = 10 ** (gain_db / 20)` computation and its use in the
   ffmpeg `volume=` filter remain untouched.
2. `backend/app/core/config.py` (`sfx_gain_db`/`sfx_max_clip_s`, lines
   181–182) — reverted the dangling uncommitted working-tree values back
   to the committed defaults:
   - `sfx_gain_db`: `-13.0` → `-8.0`
   - `sfx_max_clip_s`: `0.8` → `1.5`

**Verification performed:**

- `git diff --stat` on both files is now **empty** — both match HEAD
  exactly; the entire uncommitted diff flagged in A4/D1 no longer exists.
- `ast.parse` on `sfx.py`: syntax OK.
- No `print(` calls remain anywhere in `sfx.py`.
- No tests were run (per instruction: no e2e); nothing else in the tree
  was modified — `.gitignore` modifications and `docs/plans/analysis.md`
  itself predate this task and are untouched by it.

**Effects / reviewer notes:**

- The `1.5`s ceiling restores R15's curation: stinger (1.242s) and
  transition (1.013s) clips fit intact again instead of being trimmed
  mid-hit.
- `-8.0` becomes C3c's normalization target when task 6 lands.
- ⚠ Per D2's warning, still live until task 2 ships: a newly rendered
  project would again select the weak `swosh_swoosh` whoosh under the
  restored `1.5` ceiling. This is expected and intended — task 2 (whoosh
  off for `retention_fast`) is what fixes the symptom.
- Already-rendered projects are unaffected retroactively (their outputs
  were baked under whichever config produced them).

*(Bookkeeping 2026-08-24, per review RV4: P2 has since added lines to
`sfx.py` for the whoosh gate, so `sfx.py` no longer appears diff-clean in
`git status`. This entry's "diff-clean" claim described the state at P1's
completion; P1's revert itself remains intact.)*

### P2 — Whoosh off for `retention_fast` (2026-08-24)

**Scope executed:** sequencing step 2 only — decisions 5 + 5a. The WHOOSH
SFX layer becomes style-gated; `retention_fast` is the only style that
gates it off.

**Changes (6 files, +101/−4):**

1. `backend/app/script/styles.py`
   - New field `whoosh_enabled: bool = True` on `StylePacingBand`
     (documented in the class docstring: a plain bool, not the Optional
     shape, because there is no settings-level master switch behind it).
   - `retention_fast` band sets `whoosh_enabled=False`.
   - New resolver `resolve_sfx_whoosh_enabled(style) -> bool`, same
     fallback shape as `resolve_narration_speed`: unknown/unset styles
     resolve to `True`.
2. `backend/app/renderer/sfx.py` — `derive_sfx_events` drops all
   `WHOOSH` events after sorting when the timeline's style gates them
   off. Stinger and transition events untouched (D3: they are rare even
   on fastcut reels — transitions never fire on cuts-only styles).
3. `backend/app/renderer/fingerprint.py` — new unconditional payload
   entry `"sfx_whoosh_enabled"` (+ signature param), per the R2 rule.
   Style-derived so `render_style` already moved it indirectly, but
   hashed explicitly as a real mux input.
4. `backend/app/workflow/steps/render.py` — resolves the gate once beside
   `music_gains` (leftover-item-5 pattern: fingerprint and event
   derivation cannot drift) and passes it into the fingerprint call.
5. `backend/tests/unit/renderer/test_sfx.py` — two new tests:
   retention_fast drops whoosh but keeps stingers;
   archival/stillness/unset styles keep whoosh.
6. `backend/tests/unit/renderer/test_fingerprint.py` — helper gains the
   new kwarg; regression test proves flipping the gate changes the
   fingerprint.

**Verification performed (unit only — no e2e, DB untouched):**

- `pytest tests/unit/renderer/test_sfx.py tests/unit/renderer/
  test_fingerprint.py --noconftest`: **47 passed** (incl. 3 new tests),
  re-run green after black formatting.
- `ruff check` on all six files: clean. `black`: clean (two pre-existing
  multi-line signatures in `styles.py` that black wanted to collapse were
  deliberately reverted — not this task's diff).

⚠ **Reviewer note — conftest incident during verification:** the first
pytest invocation hung because `backend/tests/conftest.py` carries an
AUTOUSE `clean_database` fixture that TRUNCATES the real Postgres before
every test — including these pure unit tests. The hang was on the DB
connection itself (no truncate executed; nothing was lost), the hung
processes were killed, and the run was repeated with `--noconftest`,
which works because both files are pure functions of the schema. This
confirms analysis.md's ⚠ warning is broader than stated: it is not just
the e2e suite — ANY pytest run under `backend/tests/` without
`--noconftest` endangers the 7 real projects. Recommend a follow-up:
gate `clean_database` on an env var or move it out of the autouse path
for unit tests (not done here — out of scope for this task).

**Effects / reviewer notes:**

- A `retention_fast` reel that previously mixed ~106 whoosh events now
  mixes zero; its audible SFX layer becomes stingers-on-text-cards only.
  Archival/stillness behaviour is unchanged byte-for-byte in intent.
- Every existing render's fingerprint changes once (new payload key), so
  the next render of each project re-renders for real — correct and
  harmless per the R2 convention (a cache MISS is "render again", never
  "serve wrong bytes").
- Deliberate scope choice: `SelectSfxStep` still downloads a whoosh clip
  for `retention_fast` projects (it now sits unused at render time).
  Skipping selection too would be a small follow-up inside select_sfx.py;
  kept out to hold this task to the smallest symptom fix, per sequencing.
- Decision 3's restraint policy (first-punch + ~1.5s gap) remains
  deferred until whoosh is re-enabled — unchanged by this task.

### P3 — C1 BGM upload (2026-08-24)

**Scope executed:** sequencing step 3 — C1 built per C1a with resolved
decisions 2 (`act_beds=[]`), 6a/6b (warn-don't-reject on length), and 7
(gain slider entering the fingerprint).

**Changes (backend):**

1. `backend/app/assets/validation.py` — new
   `validate_and_identify_audio(content, *, ffprobe_binary) -> (extension,
   duration_s)`, the ffprobe mirror of `validate_and_identify_video`
   (A27): positively confirms a real audio stream with positive duration;
   size-capped; length NEVER rejects (6a/6b); extension derived from
   ffprobe's own `format_name` mapped through a table (mp3/wav/flac/
   ogg/m4a — oga folds into ogg). A video container carrying audio maps
   to m4a (documented in the docstring).
2. `backend/app/assets/music_upload.py` (NEW) — pure
   `music_upload_warnings(track_duration_s, video_duration_s | None)`:
   the 6a "will loop ~N times" / 6b "using the first X of Y" messages.
   No I/O, trivially unit-testable.
3. `backend/app/schemas/timeline.py` —
   `MusicTrackSelection.gain_offset_db: float = 0.0`. Default 0.0 keeps
   every provider-selected track and old timeline byte-identical in
   behaviour.
4. `backend/app/renderer/fingerprint.py` — `music_gain_offset_db` param +
   unconditional payload entry (R2 rule).
5. `backend/app/workflow/steps/render.py`:
   - offset resolved ONCE beside `music_gains` and fed to BOTH the
     fingerprint and `mux_music` (single-resolution pattern; applied to
     the BED gain only — duck depth untouched);
   - `_music_file()` now globs `{content_hash}.*` instead of hard-coding
     `.mp3` (C1a #1 — the crash-on-wav fix);
   - `_sfx_overlays` gets the identical glob fix (shared bug, flagged for
     C3f's future uploads).
6. `backend/app/api/projects.py` — `MusicUploadResult(WorkflowTriggerResult)`
   (+ `warnings: list[str]`) and `POST /{project_id}/music/upload`:
   - ffprobe-validates at the endpoint (bad bytes → 400, A27);
   - stores bytes at `storage/{project}/music/{sha256}.{real_ext}`;
   - `append_version(produced_by=HUMAN, owns={"music_plan"})` sets
     `selected_track` (provider=`project_music`,
     licence=`user_supplied`, attribution crediting the filename,
     `gain_offset_db`), `selection_attempted=True`, and **explicitly
     `act_beds=[]`** (decision 2 / C1a #5 — without it the ≥2-bed branch
     silently wins and plays the wrong audio);
   - resumes through `_resume_after_human_correction` (re-approve if
     already approved, backgrounded engine);
   - returns the trigger result PLUS the length warnings computed against
     the active timeline's total shot duration;
   - slider bounded to −40…+24 dB (400 outside) so a fat-fingered value
     cannot push the bed into clipping or silence.

**Changes (frontend):**

7. `lib/types.ts` — `MusicUploadResult extends WorkflowTriggerResult`
   with `warnings: string[]`.
8. `lib/api.ts` — `uploadMusic(projectId, file, gainOffsetDb?)` using the
   existing FormData pattern.
9. `lib/queries.ts` — `useUploadMusic` mutation (same invalidate tail).
10. `pages/Result.tsx` — the "Try different music" card gains an upload
    control (audio accept list), the dB offset number input (−40…+24),
    and a toast surfacing the server's warnings BEFORE the standard
    progress-page hop.

**Tests (unit only — DB untouched throughout):**

- NEW `backend/tests/unit/assets/test_music_upload.py`: 5 pure-warning
  cases + 5 real-ffprobe validator cases (wav round-trip with duration,
  mp3 round-trip, garbage bytes rejected, size cap enforced before any
  probing, video-only file rejected for having no audio stream).
- `test_fingerprint.py`: helper gains `music_gain_offset_db`;
  regression proves flipping it changes the fingerprint.

**Verification performed:**

- `pytest tests/unit/assets/test_music_upload.py
  tests/unit/renderer/test_fingerprint.py tests/unit/renderer/test_sfx.py
  --noconftest`: **58 passed** (incl. real ffmpeg encodes).
- `ruff check` + `black --check`: clean on every touched backend file.
- `tsc -b` (frontend): clean. One missing import caught and fixed.
- No e2e run (per the corrected ⚠ note above); manual "does it sound
  right" verification against the 7 real projects still requires the
  running service and is deliberately left for after review.

**Effects / reviewer notes:**

- Every existing render's fingerprint changed once more (new payload
  key) → one deliberate full re-render per project on next render. Same
  harmless-MISS convention as always.
- The upload path reuses the correction family's exact plumbing, so
  approve-state handling, concurrency claims, and fingerprint-driven
  re-render were all already proven behaviour — nothing new there.
- v1 scope notes: long tracks trim from the start (no `start_offset_s`),
  short tracks loop hard (no crossfade), loudness is slider-only (the
  `loudnorm` default-setting pass remains the named follow-up) — all
  three are the recorded decision 6a/6b/7 choices, not oversights.
- Note for the reviewer: `backend/tests/unit/script/test_styles.py`
  carries YOUR RV5 addition in the working tree (untouched by this task).
- ⚠ Reviewed and fixed as RV6 (below): the `mux_music` call above applied
  `music_gain_offset_db` to the bed gain only, which inverted ducking
  below roughly −4 to −6 dB depending on style — see RV6 for the measured
  figures and the fix.

### P4 — C2 provider verification + seeded tiebreak (2026-08-24)

**Scope executed:** sequencing step 4 — C2.1 (decision 1's verification)
and C2.2 (the M10 seeded pick, "the actual still-live root cause").

#### C2.1 — provider config verification (decision 1)

Static chain verified end to end:

- `.env:153` — `MUSIC_PROVIDER=openverse` remains **commented out**;
- `docker-compose.yml` passes `.env` to the backend via `env_file`, so a
  commented line means the variable is simply ABSENT in the container;
- `config.py` default `music_provider="local"` therefore applies;
- in-process check confirms it: `settings.music_provider == 'local'`.

⚠ The LIVE-process check is **still open, mechanically blocked**: Docker
Desktop is not running on this machine, so there is no container to
inspect. When the service is next started, run
`docker exec <backend-container> printenv MUSIC_PROVIDER` (expect empty)
— per decision 1, Openverse stays registered-but-unused either way, and
this check only closes the loop on what the plan already suspected.

#### C2.2 — the seeded pick (the mandatory fix)

**Changes (3 files):**

1. `backend/app/assets/music_ranking.py` — new pure function
   `pick_seeded_top(ranked, *, query_terms, video_duration_s,
   mean_shot_duration_s, seed)`: among candidates that tie with the best
   on `(duration_floor, tempo_band)` AND sit within
   `_SEED_RELEVANCE_EPSILON = 0.05` of its relevance, pick by
   `sha256("{seed}:{source_id}")`. `rank_music_candidates` itself is
   untouched and stays pure, exactly as the plan required.

   **The epsilon is load-bearing, not decoration**: an exact-ties-only
   seed would have fixed NOTHING for B2's reported symptom, because
   "Documentary Music Strings" wins relevance OUTRIGHT for every
   documentary-ish brief — there are no exact ties to break. The band of
   near-equivalents is where variety can operate; outside it, quality
   still owns the decision and no seed can promote anything.
2. `backend/app/workflow/steps/select_music.py` — `_select` calls
   `pick_seeded_top(..., seed=ctx.project_id)` after licence-gating,
   ranking, and the C7 exclude-filter, then iterates
   `[chosen] + rest` in its fetch loop (so a fetch failure falls through
   to the next-ranked candidate exactly as before). Empty-pool guard
   added (`return None`), preserving A22 semantics.
3. `backend/tests/unit/assets/test_music_ranking.py` — 7 new tests:
   per-project determinism (I5); different projects → different picks
   across 8 seeds; seed can NEVER promote a below-floor candidate; seed
   can NEVER promote a clearly-worse match (epsilon guard); single-
   candidate pool; empty pool raises.

**Verification performed:**

- `pytest tests/unit/assets/test_music_ranking.py --noconftest`:
  **22 passed** (15 pre-existing ranking/floor/tempo tests still green +
  the 7 new ones).
- Broader sweep `tests/unit/assets/`: **121 passed, 3 errors** — all 3
  are SETUP errors on Postgres connection in the known DB-dependent
  files (`test_constraint_check`, `test_depiction_check`), expected with
  no database running and unrelated to this change.
- ruff/black clean on all three touched files.
- Two defects caught by failing runs during development and fixed before
  any green claim: missing `import hashlib`, and ruff UP012 on a
  redundant encode argument.

**Effects / reviewer notes:**

- No render-fingerprint input changes: the seeded pick happens at
  SELECTION time and is recorded in `music_plan.selected_track`; the
  timeline document already carries that into the fingerprint. Existing
  projects keep their baked renders untouched.
- Same project + same candidate pool → same track forever (I5 holds);
  two projects with the same brief now diverge — the B2 defect ("all
  three projects got 'Documentary Music Strings'") cannot recur through
  this path regardless of whether the provider is local or openverse.
- Deliberately NOT seeded: SFX selection (whoosh) — deferred with C3a/C3e
  until whoosh is re-enabled; seeding a disabled layer would be dead code.
- `_SEED_RELEVANCE_EPSILON = 0.05` is a starting constant chosen by
  reasoning over the 0–1 overlap scale, not measured against a corpus —
  same epistemic status as `_ABSOLUTE_FLOOR_S` was at its introduction.
  If real pools show all candidates inside or outside the band too often,
  it is one number to retune.

### P2a — Review fixes RV1–RV4 (2026-08-24)

**Scope executed:** all four findings from the P1+P2 review, applied
before sequencing step 3 begins (RV3 explicitly required the conftest
gate to land first). Nothing else touched.

**Changes per finding:**

1. **RV1 (🔴) — `backend/scripts/c8_probe.py`**: added the missing
   `sfx_whoosh_enabled=True` kwarg to its `compute_render_fingerprint`
   call. The probe script is runnable again.
2. **RV2 (🟡) — drift invariant made real** (reviewer's preferred
   option): `derive_sfx_events` now takes `whoosh_enabled: bool` as a
   **required keyword-only parameter** and no longer resolves anything
   internally (the `app.script.styles` import was removed from `sfx.py`).
   `_sfx_overlays` threads it through, and `render.py` hands the ONE
   resolved value both to the fingerprint call and to `_sfx_overlays`.
   The render.py comment now states what actually happens ("one
   resolution feeding both consumers") instead of the false claim. All
   six `derive_sfx_events` call sites in tests pass it explicitly —
   there is no default, so a future caller cannot silently fork the
   invariant.
3. **RV3 (🟡) — conftest truncation gated**:
   - `backend/tests/conftest.py`: `clean_database` yields WITHOUT
     touching Postgres unless `PYTEST_TRUNCATE_DB=1`. An env-var gate
     (not a unit-test carve-out) because several `tests/unit/` files
     genuinely use the DB via `async_session_factory` and rely on the
     truncate for isolation — carving out `tests/unit/` would have
     broken their isolation silently.
   - `Makefile`: `make test` sets `PYTEST_TRUNCATE_DB=1`, so the
     documented full-suite workflow is byte-for-byte what it was.
   - The ⚠ paragraph above (Effort estimate section) rewritten to state
     the hazard correctly.
4. **RV4 (⚪)** — `resolve_sfx_whoosh_enabled`'s docstring corrected:
   unknown names resolve to True; UNSET inherits
   `settings.default_render_style`'s band (True today only because that
   default is `documentary_archival`). P1 bookkeeping note added (see
   above). The benign over-invalidation note (RV4 bullet 2) needs no
   code change; left as disclosed in P2.

**Verification performed:**

- `pytest tests/unit/renderer/test_sfx.py tests/unit/renderer/
  test_fingerprint.py --noconftest`: **47 passed**.
- Through-conftest run (`pytest tests/unit/renderer/test_sfx.py`,
  NO env var): **6 passed in 0.26s** — autouse fixtures active,
  Postgres never contacted (fast completion proves no connection wait).
  This is the RV3 fix demonstrated live.
- `ruff check` / `black --check`: clean on every file this task touched.
  Two pre-existing conditions deliberately NOT fixed (not this task's
  diff, verified present at HEAD via stash): ruff I001 import-sort +
  black reformat in `scripts/c8_probe.py`, black reformat of two old
  signatures in `styles.py`.
- One defect caught and fixed during verification itself: the RV2 edit
  initially removed the resolver import but left the function body
  calling it (NameError); the failing test run caught it immediately and
  the body was switched to the parameter before any green claim.

**Effects / reviewer notes:**

- Default pytest behaviour is now SAFE-BY-DEFAULT everywhere under
  `backend/tests/`; the destructive path requires the explicit env var.
- `derive_sfx_events`'s signature changed (breaking for any external
  caller) — grep confirms production has exactly one caller chain
  (`render.py::_sfx_overlays`) plus the tests, all updated.


---

## Review of P1 + P2 — 2026-08-24

Independent review of the two entries above. Findings only; **nothing was
changed in the code as part of this review.**

### Verified good (re-checked, not taken on trust)

- **P1's revert holds.** `backend/app/core/config.py` no longer appears in
  `git status --porcelain`; it matches HEAD exactly. No `print(` remains
  anywhere in `backend/app/renderer/sfx.py`.
- **P2's test claim holds.** Re-ran
  `pytest tests/unit/renderer/test_sfx.py tests/unit/renderer/test_fingerprint.py --noconftest -q`
  → **47 passed**.
- **The gate is correctly placed for I5.** The whoosh filter runs *after*
  `events.sort(...)`, so relative event order is preserved.
- **No circular import.** `app/script/styles.py` imports only `settings`;
  nothing from `app/renderer`, so `sfx.py`'s new import is safe.
- **Stinger and transition events are genuinely untouched**, matching D3.

### 🔴 RV1 — broken caller not in P2's file list

`sfx_whoosh_enabled` was added as a **required keyword-only** parameter
(confirmed by AST inspection of the signature — `kw_defaults` is `None`
for it, so there is no default). `backend/scripts/c8_probe.py:194-215`
still calls `compute_render_fingerprint` without it:

```python
sfx_gain_db=-8.0,
sfx_max_clip_s=1.5,
ffmpeg_version="7.1.5",   # ← no sfx_whoosh_enabled
```

That call now raises `TypeError` on invocation. It is a performance probe
script rather than a production path, so nothing user-facing breaks — but
it **is** broken, it was not in P2's stated "6 files", and it was not
caught because the verification run was scoped to two test files.
`tests/integration/test_render_fingerprint_cache.py` is unaffected: it
reaches the fingerprint through `render_video`, which does pass the new
kwarg.

**Fix (not applied):** add `sfx_whoosh_enabled=True,` to the probe's call.

### 🟡 RV2 — the "cannot drift" justification is false (R4-shaped)

`render.py:296-299` claims:

> *resolve once beside the music gains so the fingerprint and
> `derive_sfx_events` cannot drift (leftover item 5 / R2's own lesson).*

The code does not do this. `derive_sfx_events(timeline, fps=fps)` never
*receives* the resolved value — it calls
`resolve_sfx_whoosh_enabled(timeline.metadata.render_style)` **again,
internally** (`sfx.py:80`). The gate is resolved twice, independently.

Contrast the pattern it names: `music_gains` is one `MusicGains` object
resolved once and handed to **both** the fingerprint and `mux_music` —
that is what makes drift structurally impossible. Here the real invariant
is only *"both happen to re-derive from the same field"*, which is true
today and breaks silently the moment `_sfx_overlays` is handed a
different timeline object than the fingerprint was, or another caller of
`derive_sfx_events` appears. That is exactly the R2 failure class: the
fingerprint asserts one thing while the mix does another, so a cache HIT
serves wrong bytes.

Severity: **the code is correct today; the stated reason is not.** §15
already records `sfx_content_hashes`'s wrong justification as worth
flagging for precisely this reason — so this belongs in the log rather
than being quietly left.

**Fix (not applied), two options:** thread `whoosh_enabled` into
`derive_sfx_events`/`_sfx_overlays` as an explicit parameter so the
comment becomes true; or drop the "cannot drift" claim and state the
weaker guarantee honestly. Preferring the former, since the codebase's
own precedent is to make the invariant real.

### 🟡 RV3 — P2's conftest incident is accurate, understated, and should be promoted

Confirmed independently: `backend/tests/conftest.py:19-34` is
`@pytest_asyncio.fixture(autouse=True) async def clean_database()`, and it
runs `TRUNCATE TABLE {all tables} RESTART IDENTITY CASCADE` **before every
test** — unit tests included, because the fixture is autouse at the root
conftest.

Consequently **this document's own ⚠ note above (the "e2e/integration
tests cannot be run" paragraph) is materially wrong** and should be
corrected: the hazard is not the e2e suite, it is *any* `pytest`
invocation under `backend/tests/` without `--noconftest`. Even
`pytest tests/unit/renderer/test_sfx.py` would truncate the live Postgres
and destroy the 7 rendered projects.

P2 files this as "a follow-up, out of scope." **Recommend raising its
priority above sequencing step 3**: step 3 (C1 BGM upload) explicitly
depends on those 7 projects for the manual "does it actually sound right"
verification, and building it will mean running unit tests repeatedly.
Gate `clean_database` on an env var (or move it off the autouse path for
unit tests) *before* step 3 begins, not after.

### ⚪ RV4 — minor notes, no action required

- **`resolve_sfx_whoosh_enabled`'s docstring overstates its guarantee.**
  "Unknown / unset styles resolve to `True`" holds for *unknown* names
  (band is `None` → `True`), but *unset* resolves via
  `STYLE_PACING_BANDS.get(settings.default_render_style)` — i.e. it
  inherits whatever the default style says, and is `True` only because
  `default_render_style` is `documentary_archival` (`config.py:278`). If
  that default ever became `retention_fast`, unset would silently gate
  whoosh off. The behaviour is right and faithfully copies
  `resolve_narration_speed`'s shape; only the wording is loose.
  `test_other_and_unset_styles_keep_whoosh` passes for the same
  incidental reason.
- **`_sfx_content_hashes` still carries the whoosh hash on
  `retention_fast`**, since `SelectSfxStep` still downloads the clip (a
  deliberate scope choice P2 disclosed). Harmless over-invalidation:
  re-curating the whoosh library would force fastcut projects to
  re-render with no audible change. Errs in the safe direction.
- **P1's entry reads as though `sfx.py` is diff-clean** ("`git diff
  --stat` on both files is now **empty**"). That was true when written;
  P2 has since added +8 lines to it. Bookkeeping only — P1's actual
  revert is intact.

### Follow-up — RV1–RV4 fixed, RV5 found and fixed (2026-08-24)

**RV1.** `backend/scripts/c8_probe.py:214` now passes
`sfx_whoosh_enabled=True,` in its `compute_render_fingerprint(...)` call,
alongside the other `sfx_*` kwargs. The probe's `TypeError` is gone.

**RV2.** Fixed the preferred way named above — by threading the parameter,
not by softening the comment. `render.py:302` resolves
`sfx_whoosh_enabled = resolve_sfx_whoosh_enabled(timeline.metadata.render_style)`
once, beside `music_gains`, and hands that single value to both
`compute_render_fingerprint` (`render.py:325`) and `_sfx_overlays`
(`render.py:470`), which passes it through to `derive_sfx_events` as a
required keyword-only parameter (`sfx.py:53`). `derive_sfx_events` no
longer calls `resolve_sfx_whoosh_enabled` internally, and `sfx.py`'s
`from app.script.styles import ...` line is gone — the renderer→script
coupling RV2 flagged as a symptom is removed along with the bug.

**RV3.** `backend/tests/conftest.py:24-58`'s `clean_database` now checks
`os.environ.get("PYTEST_TRUNCATE_DB") != "1"` and does `yield; return`
before touching the database when unset — matching the fixture's own
updated docstring ("2026-08-24 (review of P2, analysis.md RV3)"). Default
behaviour for any bare `pytest tests/unit/...` invocation is now no
truncation. `Makefile`'s `test:` target sets
`PYTEST_TRUNCATE_DB=1` ahead of the full-suite `pytest` invocation, so the
documented "one full-suite run, alone, in the foreground" workflow is
unchanged.

**RV4.** `resolve_sfx_whoosh_enabled`'s docstring (`styles.py:184-196`) now
says explicitly: unknown style names resolve to `True` because there is no
band to consult, while an *unset* style resolves through
`settings.default_render_style`'s own band and is `True` today only
because that default is `documentary_archival` — not because unset is
pinned open independently of the registry. This matches the actual
behaviour RV4 confirmed; only the wording was loose before.

**RV5 — new finding, closed.** The RV2 fix is correct, but it moved style
resolution *out* of `derive_sfx_events` and into the caller. That silently
gutted the two tests that had covered the style→bool mapping:
`test_retention_fast_drops_whoosh_but_keeps_other_kinds` and
`test_other_and_unset_styles_keep_whoosh` in
`tests/unit/renderer/test_sfx.py` each set
`timeline.metadata.render_style = ...` and then passed `whoosh_enabled=`
explicitly — so the style assignment was inert, and neither test exercised
`resolve_sfx_whoosh_enabled` at all. `resolve_sfx_whoosh_enabled` itself
had zero direct test coverage. A regression that deleted
`whoosh_enabled=False` from `retention_fast`'s band would have passed the
entire suite. Closed by adding
`test_retention_fast_gates_whoosh_off_and_others_stay_on` to
`tests/unit/script/test_styles.py` (covering `retention_fast` → `False`;
`documentary_archival`, `stillness`, and an unknown name → `True`; and
`None` → `True` via `default_render_style`, with a comment distinguishing
that from unset being pinned open) and by fixing the two `test_sfx.py`
tests to describe what they actually assert: renamed to
`test_whoosh_enabled_false_drops_whoosh_but_keeps_other_kinds` and
`test_whoosh_enabled_true_keeps_whoosh`, with the now-inert
`render_style` assignments removed, the three-style loop in the latter
collapsed to a single case (style no longer influences the call), and a
comment in each pointing at `test_styles.py` as where the style→bool
mapping is now covered.

⚠ No action taken on two pre-existing, unrelated items noticed along the
way:

- `Makefile`'s `test:` target (`PYTEST_TRUNCATE_DB=1 $(PY) -m pytest ...`)
  uses POSIX env-prefix syntax. That's fine under Git Bash — the
  Makefile's own header names Git Bash as the Windows fallback when `make`
  isn't on PATH — but the same line would fail outright under `cmd.exe`.
  It fails loudly rather than silently skipping truncation, which is the
  safe direction to break in, so this is a note, not a fix.
- The `I001` ruff import-sort error in `scripts/c8_probe.py` is
  pre-existing and unrelated to this work — confirmed by running
  `ruff check` against the HEAD version of the file, which fails
  identically.

**Verification actually run** (all under `backend/`, all with
`--noconftest`, all scoped to `tests/unit/`):

```
python -m pytest tests/unit/script/test_styles.py tests/unit/renderer/test_sfx.py tests/unit/renderer/test_fingerprint.py --noconftest -q
```
→ 67 passed.

```
python -m ruff check tests/unit/script/test_styles.py tests/unit/renderer/test_sfx.py
python -m black --check tests/unit/script/test_styles.py tests/unit/renderer/test_sfx.py
```
→ ruff: clean on both files. black flagged pre-existing formatting drift
in `test_styles.py` at lines unrelated to this change (`test_draft_format_
follows_the_style_aspect`, `test_music_gains_are_style_owned_and_archival_
keeps_the_measured_mix`); confirmed pre-existing by running the same
`black --check` against the HEAD copy of the file, which fails identically
— not introduced by this change, left alone per instructions.

No test outside `tests/unit/` was run, `PYTEST_TRUNCATE_DB` was never set,
and no database-touching command was run.

### RV6 — new finding (review of P3), the gain slider inverted ducking

Found while reviewing P3 (C1 BGM upload), not P1/P2 — logged here anyway
since this is the running review log for the whole sequence.

**What was wrong.** `render.py`'s `mux_music` call applied the human's
`music_gain_offset_db` slider to the bed gain only:

```python
bed_gain_db=music_gains.bed_gain_db + music_gain_offset_db,
duck_gain_db=music_gains.duck_gain_db,   # offset NOT applied
```

(the exact lines P3 added — see `render.py`'s previous
`_resolve_music_track`/`mux_music` call, right after `assemble_act_bed`).
The adjacent comment claimed *"the slider controls loudness, not duck
depth"* — the code did the opposite. `app/renderer/music.py:158-170`
(`_volume_chain`) builds the envelope as an unconditional
`volume=bed_linear` across the whole stream, then multiplies by
`relative_duck = duck_linear / bed_linear` (line 163) inside each
narration window. That ratio, multiplied against the base, always
resolves to exactly `duck_linear` inside a window — i.e. the level during
narration is the ABSOLUTE `duck_gain_db`, entirely independent of the
bed. Lowering only the bed therefore does not lower the ducked floor at
all; it raises `relative_duck` instead, and once the bed drops far enough
below the (unmoved) duck gain, `relative_duck` exceeds 1.0 and ducking
**inverts** — music gets louder, not quieter, under narration, which is
the opposite of what a human turning the slider down is asking for.

**Measured inversion**, across the three styles' bed/duck pairs
(`resolve_music_gains`, `styles.py`):

| style | bed / duck | ducking inverts at offset | at offset −40 |
|---|---|---|---|
| `retention_fast` | −10 / −14 | −4 dB | music ~63× louder under speech |
| `documentary_archival` | −14 / −20 | −6 dB | ~50× |
| `stillness` | −22 / −28 | −6 dB | ~50× |

Most of the slider's documented −40…+24 dB range's negative half is
broken, and "the music is too loud, turn it down" is the single most
likely reason anyone touches this control.

**Why it escaped.** `test_music_gain_offset_changes_the_fingerprint`
(`tests/unit/renderer/test_fingerprint.py`) asserts only that the
fingerprint changes when the offset changes — it never exercises the
bed/duck interaction the offset actually feeds into. The whole test
suite passed with the inversion present. Same shape as RV5: a new input
got a fingerprint test but no behaviour test.

**The fix.** Apply the offset to both gains, so the duck DEPTH
(`bed_gain_db - duck_gain_db`) is preserved and the whole envelope shifts
together instead of the floor staying pinned while the bed above it
moves. Landed as a small named, documented, pure function,
`offset_bed_and_duck_gain_db` (`app/renderer/music.py`), used by
`render.py`'s `mux_music` call in place of the inline one-sided
arithmetic, with the adjacent comment corrected to describe what the
code now does. Confirmed no other consumer needs the same treatment:
`assemble_act_bed`/`_music_segments` (the per-act bed path) only
loop/trim/concat raw audio files — no gain is ever applied there, so the
Path A (single track) and Path B (≥2 act beds) cases share one gain
application point in `mux_music` and cannot double-count.

Regression test: `test_gain_offset_never_inverts_ducking` plus two
supporting tests in the new `tests/unit/renderer/test_music.py` — pure
arithmetic, no ffmpeg/DB — assert `duck_gain_db < bed_gain_db` and a
preserved depth across all three styles and offsets
{−40, −20, −10, −6, −4, 0, +12, +24}, and separately that
`_volume_chain`'s own `relative_duck` ratio stays below 1.0. Confirmed
load-bearing: reverting `offset_bed_and_duck_gain_db` to the old
one-sided formula reproduces the measured figures above exactly
(`retention_fast` at −40 → `relative_duck == 63.09...`) and fails the new
tests; restoring the fix passes them again.

Found in review of P3 before any render ever used the slider (it ships
in the same commit as the feature) — no shipped render output is
affected.

### Status

| Finding | Severity | Fixed? |
|---|---|---|
| RV1 — `c8_probe.py` missing required kwarg → `TypeError` | 🔴 real defect | ✅ fixed |
| RV2 — false "cannot drift" justification (R4-shaped) | 🟡 wrong reason, correct code | ✅ fixed |
| RV3 — conftest truncates on *every* pytest run; doc understates it | 🟡 process risk to the 7 projects | ✅ fixed |
| RV4 — docstring wording, benign over-invalidation, P1 bookkeeping | ⚪ minor | ✅ fixed |
| RV5 — RV2's fix silently gutted the style→bool test coverage; `resolve_sfx_whoosh_enabled` had none | 🟡 test-coverage gap | ✅ fixed |
| RV6 — BGM gain slider offset applied to bed only, inverting ducking below ~−4 to −6 dB | 🔴 real defect (slider mostly broken) | ✅ fixed |

### P5 — C3f SFX upload/disable per kind (2026-08-24)

**Scope executed:** sequencing step 5 — decision 4's chosen surface
exactly: **upload + per-kind disable, no clip-picker UI**. The optional
`/sfx/retry` reset endpoint was deliberately NOT built (the plan marked
it optional; nothing needs it while whoosh is gated off for
`retention_fast` — a retry would just re-select the same local-library
clips). *(⚠ Superseded by P5a/RV8: `/sfx/retry` WAS built during the
review fixes — the original skip-reasoning covered whoosh only and
ignored that stinger and transition are equally unrecoverable without
it.)*

**Changes (4 files):**

1. `backend/app/assets/sfx_override.py` (NEW) — pure
   `apply_sfx_clip_override(clips, kind, replacement)`: returns a NEW
   list with every clip of `kind` removed, `replacement` appended when
   given (`None` = disable). Never mutates the input (I3). The endpoint
   stays a thin I/O shell over this testable core, mirroring the
   `music_upload_warnings` pattern from P3.
2. `backend/app/api/projects.py` — new
   `POST /projects/{id}/sfx/{kind}/override`:
   - `kind` is validated by FastAPI against the `SfxKind` enum
     (whoosh/stinger/transition → 422 on anything else);
   - **file supplied** → ffprobe-validated at the endpoint (A27), hashed,
     stored at `storage/{project}/sfx/{sha256}.{real_ext}`; that kind's
     entry replaced with provider=`project_sfx`,
     licence=`user_supplied` (A24). The `_sfx_overlays` glob fix from P3
     means non-mp3 uploads resolve at render time;
   - **no file + `enabled=false`** → every clip of that kind REMOVED.
     Disable costs nothing extra: the renderer's `by_kind.get(kind)` miss
     already skips an absent kind, and `sfx_content_hashes` shrinking
     changes the fingerprint → correct re-render;
   - **neither / both** → 400 with an explanatory message;
   - recorded via `_resume_after_human_correction(owns={"sfx_plan"})` —
     HUMAN provenance (I3), re-approve-if-approved, backgrounded resume.
3. `backend/tests/unit/assets/test_sfx_override.py` (NEW) — 6 tests on
   the pure helper: replace-preserves-others; replace re-enables a
   previously disabled kind; disable removes only that kind; disabling an
   absent kind is a no-op; stale duplicates of a kind are all removed;
   input list never mutated (I3).

**Verification performed:**

- `pytest tests/unit/assets/test_sfx_override.py --noconftest`: **6
  passed**; ruff clean; black clean (after formatting the new test file).
- Import smoke check: `app.api.projects` imports cleanly and its router
  exposes `/projects/{id}/sfx/{kind}/override`.
- No DB touched; no e2e run (deferred per the corrected ⚠ note).

**Effects / reviewer notes:**

- No new fingerprint inputs needed: `sfx_content_hashes` already covers
  clip content, so both operations (replace changes hashes, disable
  shrinks the list) invalidate cached renders through existing plumbing.
- Lessons from RV6/RV5 applied deliberately: the only logic here is list
  filtering (no coupled parameters to mis-thread), tests assert actual
  list outcomes rather than mere cache-invalidation, and there is no
  style mapping in this feature for a coverage split to apply to.
- Scope note for reviewers: NO frontend control yet — decision 4
  specified endpoints only ("Upload + per-kind disable... no clip-picker
  UI") and no Result-page surface exists today for individual SFX kinds.
  A small UI affordance can be added later if wanted; kept out of this
  task to match the decided surface exactly.
- ⚠ ~~Per-kind disable composes correctly with task 2's style gate:
  whoosh is ALREADY absent from `retention_fast` timelines' clips at
  selection time, so disabling whoosh there succeeds as a no-op —
  harmless and consistent.~~ **WRONG (RV7, review of P5) — corrected:**
  `SelectSfxStep` has NO style gating; the whoosh *clip* IS stored in
  `sfx_plan.clips` even on `retention_fast` (only the render-time
  *events* are gated by `derive_sfx_events`). Disabling whoosh there
  removes a real clip → `_sfx_content_hashes` shrinks → fingerprint
  changes → a FULL re-render whose audio is byte-identical to before.
  Wasted work, but never wrong output — and now reversible via
  `/sfx/retry` (P5a/RV8). The latent code follow-up underneath
  (`SelectSfxStep` fetching a clip that can never play on
  `retention_fast`) remains deferred exactly as P2 recorded.
  ⚠ **This last bullet is FALSE — see RV7 below.** Left in place rather
  than silently rewritten, so the review has something to point at.

---

## Review of P5 (C3f) — 2026-08-24

Independent review of the P5 entry above. Findings only; **no code or
doc content was changed as part of this review** beyond appending this
section and the ⚠ pointer on P5's final bullet.

**Headline: P5's code appears correct.** Unlike RV1 (`TypeError`) and RV6
(a slider broken across most of its range), nothing here is functionally
broken. RV7 is a false claim over working code, RV8 is a scope decision
resting on reasoning that does not cover the cases it affects, RV9 is
latent, RV10 is a coverage gap. That is a real step up from P1–P4.

### 🟡 RV7 — the `retention_fast` "no-op" claim is false

P5's final Effects bullet claims whoosh is *"ALREADY absent from
`retention_fast` timelines' clips at selection time, so disabling whoosh
there succeeds as a no-op."*

`backend/app/workflow/steps/select_sfx.py` has **no style gating at all**
— no `render_style`, no `resolve_sfx_whoosh_enabled`, nothing (grepped).
P2's own entry says so explicitly: *"`SelectSfxStep` still downloads a
whoosh clip for `retention_fast` projects (it now sits unused at render
time)."* The style gate drops whoosh **events** in `derive_sfx_events`;
the **clip** remains in `sfx_plan.clips`.

So disabling whoosh on a `retention_fast` project is **not** a no-op: it
removes a real clip → `_sfx_content_hashes` shrinks → the fingerprint
changes → a full re-render whose audio is byte-identical, because the
events were already gated. A wasted re-render, documented as harmless.

⚠ **Fourth occurrence of the R4-shaped wrong-justification pattern** —
after `SelectSfxStep`'s "so a human hears the whooshes" (§15),
`sfx_content_hashes`' stated reason (§15), and RV2's "cannot drift".
Correct code, confident and wrong rationale attached. In a codebase whose
docs are trusted enough to be built on, this is the most consequential
defect class present, and it has now survived being flagged three times.

**Fix: documentation only.** State what actually happens. (There is a
latent code follow-up underneath — `SelectSfxStep` fetching a whoosh clip
that can never play on `retention_fast` — but P2 deliberately deferred
that; it is not new here.)

### 🟡 RV8 — disable is one-way, and the reason given for that covers only whoosh

There is no path back to auto-selection. `SelectSfxStep`'s skip check is
`bool(timeline.sfx_plan.clips) or timeline.sfx_plan.selection_attempted`
(`select_sfx.py:69`) — once `selection_attempted` is set it never
re-selects, whether one kind was disabled or all of them. **The only undo
for a disable is uploading your own audio file for that kind.**

P5 skips `/sfx/retry` reasoning that *"nothing needs it while whoosh is
gated off for `retention_fast`."* That argument covers whoosh only:

- **stinger** fires on every shot carrying a `text_card`, on **every**
  style, ungated;
- **transition** fires on non-cut transitions (`documentary_archival` /
  `stillness` dissolves).

Both are equally disable-able and equally unrecoverable. Disabling the
stinger to hear a project without it is a one-way door.

⚠ **This needs a decision, not just a fix** — decision 4 ("upload or
disable is enough") makes accepting the limitation legitimate:

1. **Accept it** → the doc must state the limitation plainly instead of
   the current whoosh-only reasoning, so nobody meets the trap blind.
2. **Build `/sfx/retry`** → small, mirrors the existing music retry
   (reset `selection_attempted=False`, clear clips, resume through
   `_resume_after_human_correction`).

Reviewer's lean: **build it.** It is cheap, and "I disabled the stinger
and cannot get it back" is reachable on the 7 real projects.

### ⚪ RV9 — `ffprobe_binary` config drift (applies to P3 as well)

Both audio call sites — music upload (`api/projects.py:2025`) and the SFX
override (`:2146`) — call `validate_and_identify_audio(content)` without
`ffprobe_binary`, taking the function's own `"ffprobe"` literal default
rather than `settings.ffprobe_binary` (`config.py:186`). They agree today
only because both defaults are the same string. Set `FFPROBE_BINARY` to
an absolute path and the renderer honours it while **both** upload
endpoints keep invoking bare `ffprobe`.

**Fix: code**, two call sites. Worth doing now precisely because the
pattern is already duplicated and will be copied a third time by C3c.

### ⚪ RV10 — the tested half is not the new half

Six tests, all on `apply_sfx_clip_override` — good tests, including I3
non-mutation and all-duplicates-removed. But that function is six lines
of list comprehension. The genuinely novel logic is the endpoint shell:
the `file` × `enabled` branching (four combinations, two of which are
400s), the storage path construction, and the `provider` / `licence` /
`track_id` fields. **None of it is covered** (no endpoint-level test
exists — grepped `backend/tests/`).

P5 states *"lessons from RV6/RV5 applied deliberately."* Half-applied: it
does assert real list outcomes rather than mere cache-invalidation, which
is the improvement. But RV5/RV6's actual lesson was *verify the part that
is not copied from an existing precedent* — and here that is the shell,
not the algebra. Same shape as before, milder.

**Fix: code** (add endpoint tests).

### ✅ Verified good

- **The pure-core / thin-shell split is the right structure** and
  consciously mirrors P3's `music_upload_warnings`. First entry where
  testability was designed in rather than retrofitted.
- **"No new fingerprint inputs needed" is correct — verified.**
  `_sfx_content_hashes` is built from `sfx_plan.clips`, so replace
  changes a hash and disable shortens the list; both invalidate through
  existing plumbing. Genuinely reasoned, not assumed.
- **Rejecting the ambiguous `file`×`enabled` combinations with 400**
  (neither / both) rather than picking a silent precedence.
- **All duplicates of a kind removed on replace**, not just the first —
  defensive, and tested.
- **Honest scope note** that no frontend exists, rather than implying the
  feature is user-reachable.
- `kind` validation is free via the FastAPI `SfxKind` enum (422).
- 6 tests pass under `--noconftest`; no DB touched during this review.

### Status

| Finding | Severity | Fix type | State |
|---|---|---|---|
| RV7 — false "disabling whoosh on `retention_fast` is a no-op" claim | 🟡 wrong reason, correct code | docs only | ✅ fixed |
| RV8 — disable is irreversible; `/sfx/retry` skipped on whoosh-only reasoning | 🟡 functional gap | **decision needed**, then docs or code | ✅ fixed (built `/sfx/retry`) |
| RV9 — both audio endpoints ignore `settings.ffprobe_binary` | ⚪ latent | code (2 call sites) | ✅ fixed |
| RV10 — endpoint branching untested; only the pure helper is covered | ⚪ coverage gap | code (tests) | ✅ fixed |

### P5a — Review fixes RV7–RV10 (2026-08-24)

**Scope executed:** all four findings from the P5 review.

1. **RV7 (🟡, docs)** — P5's final bullet corrected in place (struck
   through, replaced with what actually happens): disabling whoosh on a
   `retention_fast` project removes a real clip and triggers a full,
   audio-identical re-render — NOT a no-op. The whoosh *clip* lives in
   `sfx_plan.clips`; only the render-time *events* are style-gated.
2. **RV8 (🟡, code — reviewer's lean adopted)** — new
   `POST /projects/{id}/sfx/retry`, an exact mirror of
   `retry_music_selection`: resets `clips=[]` and
   `selection_attempted=False` via `append_version(produced_by=HUMAN,
   owns={"sfx_plan"})`, resumes through the correction family's shared
   tail. This makes disable reversible for EVERY kind — the old
   skip-retry reasoning covered whoosh only and ignored that stinger
   (every text-card shot) and transition (non-cut xfades) are equally
   disable-able and were equally unrecoverable. Uploaded override files
   stay on disk but become unreferenced.
3. **RV9 (⚪, code)** — both audio validation call sites (music upload +
   SFX override) now pass `ffprobe_binary=settings.ffprobe_binary`
   instead of relying on the function's `"ffprobe"` literal default, so
   a custom `FFPROBE_BINARY` is honoured end to end. Applied before C3c
   can copy the pattern a third time, as the review asked.
4. **RV10 (⚪, code/tests)** — NEW
   `backend/tests/unit/api/test_sfx_override_api.py`: 10 endpoint tests
   through REAL FastAPI routing (`TestClient`) with every DB dependency
   overridden and `start_workflow_run` monkeypatched at its import site.
   Coverage now includes exactly what RV10 said was missing:
   - the full `file` × `enabled` matrix: neither→400 "nothing to do",
     both→400 "conflicting", file→202+replace, disable→202+remove;
   - unknown kind → 422; missing timeline → 400; missing sfx_plan → 400;
   - valid upload (real ffmpeg wav): asserts the TRANSFORMED document —
     provider=`project_sfx`, licence=`user_supplied`, correct hash/
     track_id/attribution, other kinds untouched, bytes stored at
     `storage/{id}/sfx/{hash}.wav`, HUMAN provenance owning exactly
     `sfx_plan`, DRAFT timeline NOT self-approved, engine resumed once;
   - garbage upload → 400 naming the filename, nothing appended;
   - `/sfx/retry`: resets clips AND `selection_attempted`, HUMAN
     provenance; disable does NOT touch the attempt flag (only retry
     does).

**Verification performed:**

- `pytest tests/unit/api/test_sfx_override_api.py
  tests/unit/assets/test_sfx_override.py --noconftest`: **16 passed**
  (10 endpoint + 6 pure-helper).
- ruff/black clean on every touched file.
- No DB touched; no e2e run.

**Lessons re-applied, honestly scored:** RV6/RV5's real lesson — test
the part that is NOT copied from precedent — was only half-applied in
P5, and RV10 named it. This time the new surface (branching, storage
path, provenance fields, reset semantics) is the part under test, and
one test bug (asserting `selection_attempted` without setting it first)
was caught by a failing run and fixed before any green claim.

### P6 — C3c normalization + C3d end-aligned trim (2026-08-24)

**Scope executed:** sequencing step 6 — decision 5b's slice exactly.
C3c: every clip with a MEASURED peak lands on the `−8.0` target
(decision 5c). C3d: over-ceiling clips trim from the END so impact
transients survive. Main beneficiary per decision 5b: the stinger.

**Changes (10 files):**

1. `backend/app/assets/sfx_levels.py` (NEW) — the whole feature's brain,
   pure + probe:
   - `gain_to_target_db(peak, target)` / `effective_gain_db(peak, *,
     target_db, fallback_db, kind_offset_db=None)`: known peak →
     normalize onto target; unknown peak → flat `sfx_gain_db` fallback;
     optional per-kind dB offset rides on top of either path;
   - `end_aligned_trim_start(duration_s, max_clip_s)`: `max(0, dur −
     max)`; zero for fitting/unknown/degenerate inputs;
   - `measure_peak_dbfs(path, *, ffmpeg_binary)` — async volumedetect,
     regex-parsed, NEVER raises: any failure returns `None`, degrading to
     yesterday's flat-gain behaviour instead of failing a selection or
     upload.
2. `backend/app/schemas/timeline.py` — `SfxClipSelection` gains
   `peak_dbfs: float | None = None` and `duration_s: float | None =
   None`. Defaults keep every pre-C3c timeline byte-identical in
   behaviour; being inside the hashed timeline document means a changed
   measurement invalidates the render cache with NO new fingerprint
   inputs.
3. `backend/app/core/config.py` — `sfx_normalize_target_db = -8.0`
   (decision 5c) plus optional `sfx_whoosh/stinger/transition_gain_db`
   overrides (None = none).
4. `backend/app/workflow/steps/select_sfx.py` — after the existing
   duration probe succeeds, measures the peak and stores BOTH on the new
   `SfxClipSelection` (None under DRY_RUN).
5. `backend/app/api/projects.py` — the SFX override upload (P5) now also
   stores measured peak + validated duration on its replacement clip, so
   human uploads get identical treatment to library clips.
6. `backend/app/renderer/sfx.py` — new frozen dataclass `SfxOverlay`
   (path, offset_s, volume_factor, trim_start_s); `mux_sfx` drops its
   global `gain_db` param entirely and builds each overlay's chain from
   the overlay's own factor, with an end-aligned
   `atrim=start:end=` when `trim_start_s > 0`. Both trim branches yield
   exactly `max_clip_s` seconds, so R15's fade-out timing is unchanged.
7. `backend/app/renderer/fingerprint.py` — two new unconditional payload
   entries: `sfx_normalize_target_db` and
   `sfx_kind_gain_overrides_db` (dict; `_canonical_json` sorts keys).
   Clip peaks/durations ride in via the timeline document, so they need
   no separate entries.
8. `backend/app/workflow/steps/render.py` — `_sfx_overlays` assembles
   `SfxOverlay`s using `effective_gain_db` +
   `end_aligned_trim_start` against config; the `mux_music` call site is
   untouched.
9. `backend/scripts/c8_probe.py` — the RV1 lesson APPLIED this time:
   after changing `compute_render_fingerprint`'s signature, grepped ALL
   callers first; the probe got the two new kwargs in the same pass.
10. `backend/tests/integration/test_mux_sfx.py` — updated to the
    `SfxOverlay` signature (found by the same caller grep).

**Tests:** NEW `tests/unit/assets/test_sfx_levels.py` (10 tests): gain
math incl. both fallback paths and kind offsets; end-aligned edges
(fits/overlong/unknown/degenerate); real-ffmpeg volumedetect round-trip
asserting the KNOWN −18.1 dBFS of ffmpeg's `sine` source (1/8 amplitude)
— a stronger parse proof than "returned something"; garbage → None.
Plus fingerprint regressions for target and kind-override sensitivity.

**Verification performed:**

- Full sweep of everything touched: **152 passed** (`--noconftest`),
  including the real-ffmpeg integration `test_mux_sfx.py` under the new
  signature.
- One test failure during development, root-caused not papered over:
  my "full-scale sine" assumption was wrong (ffmpeg `sine` = 1/8
  amplitude = −18.1 dBFS); fixed by asserting the true known value.
- ruff/black clean on all touched files EXCEPT the two documented
  pre-existing conditions (`c8_probe.py` I001+black drift, `styles.py`
  two signatures), reconfirmed pre-existing earlier via stash.
- No DB touched; no e2e run.

**Effects / reviewer notes:**

- Old timelines: both new fields None → flat-gain + head-trim = byte-
  identical behaviour to before this task. Nothing retroactive.
- New renders: any clip selected/uploaded from now on carries
  measurements, so stingers land at −8 dBFS instead of their raw master
  level, and an over-long stinger keeps its transient.
- Fingerprint changes once more (two new keys) → one deliberate full
  re-render per project on next render; same harmless-MISS convention.
- Per-kind overrides default to None everywhere, so they are inert until
  someone sets them - the knob exists without changing today's sound.
- The Windows argv-length concern (A4.6/C3h) is untouched: one `-i` per
  EVENT remains, but whoosh is gated off on `retention_fast` (task 2),
  so event counts stay small until C3h lands or whoosh returns.
- ⚠ **Corrected by RV11 (review of this task, below):** `sfx_normalize_
  target_db` shipped here as `−8.0`, not C3c's own `~−12 dBFS` spec —
  see RV11 for the conflation, the measured before/after, and the fix.

## Review of P6 (C3c/C3d) — 2026-08-24

Independent review of the P6 entry above. Findings only; **no code was
changed as part of finding this** — the fix described under RV11 was
applied as a direct, uncontested correction of a wrong constant, the
same way RV1's `TypeError` and RV6's inverted slider were.

### 🔴 RV11 — the normalization target shipped as a GAIN, not C3c's PEAK target, making every real SFX clip louder

Two different quantities share the "how loud is SFX" concern and got
collapsed into one number:

- **Decision 5c** (`analysis.md:214`) is about `sfx_gain_db` — a flat
  **GAIN** applied on top of whatever level a clip already has. `−8.0`
  is a defensible answer to *that* question (revert to the value that
  predates the whoosh-taming `−13` hack).
- **C3c** (`analysis.md:150`) specifies a completely different quantity:
  the **normalization PEAK target** for `sfx_normalize_target_db` —
  *"every clip hits a target peak (**~−12 dBFS**)"*, explicitly because
  raw clip peaks span too wide a range (−0.2 to −7.3 dB in that same
  sentence) for one flat gain to serve.

Decision 5c's own text then reused the gain's answer for the target —
*"and `−8.0` becomes C3c's normalization target"* (`analysis.md:214`,
repeated at P1 `analysis.md:327` and P6 `analysis.md:1244`) — and P6
(`backend/app/core/config.py:187` pre-fix) shipped exactly that:
`sfx_normalize_target_db: float = -8.0`. The −8/−12 conflation did not
originate in P6; it originated in decision 5c and P6 faithfully
implemented what decision 5c said, without re-checking it against C3c's
own, different, number two paragraphs above it.

**Effect, measured live with `volumedetect` against the real SFX
library** (peak dBFS is each clip's own unmodified peak):

| clip | peak dBFS | old flat gain (`−8.0`) | shipped target (`−8.0`) | correct target (`−12.0`, C3c) |
|---|---|---|---|---|
| `transition/swoosh_15_windy.mp3` | −1.1 | −9.1 | −8.0 (**+1.1**) | −12.0 (−2.9) |
| `whoosh/deep_whoosh_1.mp3` | −1.9 | −9.9 | −8.0 (**+1.9**) | −12.0 (−2.1) |
| `stinger/timpani_sting.mp3` | −5.0 | −13.0 | −8.0 (**+5.0**) | −12.0 (+1.0) |
| `whoosh/swosh_swoosh_whoosh_air_sound_free_high_quality.mp3` | −7.3 | −15.3 | −8.0 (**+7.3**) | −12.0 (+3.3) |

Because every real clip in the library peaks below −8 dBFS, normalizing
onto a −8 target made **every one of them louder** than the pre-C3c
baseline, and louder in every case than the user's own hand-tuned
`−13` gain the whoosh-taming hack used. The stinger — P6's own stated
"main beneficiary" of this pass, since it fires on every text card,
ungated — got **+5.0 dB**, the worst case in the table. This is the
opposite of what C3c set out to do (tame clips that ran hot) and the
opposite of the user's actual complaint (SFX being irritating/too
loud).

⚠ **This was not a new number to derive — C3c had already specified
`~−12 dBFS`, in the same document, two entries before P6 shipped.** The
value existed; it was overwritten in transit by decision 5c reusing the
sibling gain's answer, and P6 did not cross-check the two.

**Fix applied:** `backend/app/core/config.py:197`,
`sfx_normalize_target_db` corrected `-8.0` → `-12.0`, with the field
comment now stating explicitly that it is an **absolute output peak
target in dBFS**, distinct from `sfx_gain_db`'s flat gain (which stays
`-8.0`, untouched — decision 5c's own question was answered correctly).
Pinned in `backend/tests/unit/assets/test_sfx_levels.py`: one test
asserts the two settings are different quantities/values, one asserts
a known peak (−5.0, the stinger's own measured value) against the real
`-12.0` target yields exactly −7.0 dB of gain.

**⚠ Headroom caveat, measured, not assumed — `mux_sfx` builds
`amix=...:normalize=0` (`backend/app/renderer/sfx.py`), so SFX sums
onto narration/music with no automatic level management; a −12 target
is only safe if there is room below 0 dBFS for it to land in.** Ran
`ffmpeg -af volumedetect` against real existing renders under
`backend/storage/{project_id}/renders/*.mp4` (read-only measurement, no
re-render):

| render | max_volume | mean_volume |
|---|---|---|
| `b8653f53.../renders/final.mp4` | −0.6 dB | −20.3 dB |
| `88cafc1b.../renders/final.mp4` | −1.0 dB | −20.4 dB |
| `38e586f1.../renders/final.mp4` | −1.8 dB | −20.3 dB |
| `91373658.../renders/final.mp4` | −2.4 dB | −20.3 dB |
| `fc19632f.../renders/final.mp4` | −6.8 dB | −25.0 dB |
| `3d56cf87.../renders/final.mp4` | −7.3 dB | −27.0 dB |
| `b6a2ae69.../renders/final.mp4` | −7.3 dB | −25.3 dB |
| `71e4758a.../renders/final.mp4` | −14.2 dB | −33.7 dB |
| `91373658.../renders/draft.mp4` | −17.0 dB | −37.9 dB |

Headroom is **not uniform**: four of the nine measured renders already
peak within 0.6–2.4 dB of 0 dBFS before any SFX-driven change, which
leaves very little room for an un-managed `amix normalize=0` sum to
avoid clipping; the other five sit at 6.8–17.0 dB below 0 dBFS, where a
−12 dBFS SFX layer is comfortable. `−12` is a real improvement over
`−8` for clipping risk in every case (it can only reduce or hold the
SFX layer's contribution, never raise it, since every measured library
clip already peaks below −8 dBFS), but it does not by itself guarantee
headroom on the tightest renders — that risk lives in `amix
normalize=0`, which this task did not touch and which C3c never
specified fixing.

**What is NOT concluded here:** whether −12 dBFS *sounds* right against
narration and music is a judgement call this review cannot make from
`volumedetect` numbers alone. The target is now grounded in what C3c's
text actually specifies, not verified by ear — that check is the
user's, against a real render, same as every other "does it sound
right" call in this document.

### Status

| Finding | Severity | Fix type | State |
|---|---|---|---|
| RV11 — `sfx_normalize_target_db` shipped as decision 5c's gain value (`−8.0`) instead of C3c's own peak-target spec (`~−12 dBFS`), making every real SFX clip louder (stinger +5.0 dB) | 🔴 real defect, contrary to the user's complaint and hand-tuning | config + docs + tests | ✅ fixed |

