# Plan: a source video's own baked-in letterbox never becomes a second letterbox

Status, 2026-09-14: **NOT BUILT.** Diagnosed and hand-fixed once, on project
`2148489a-2171-4087-a29a-ec0b55b60525` (4 assets, see §1). Every claim in §1-§4
was verified against the code on 2026-09-14; line numbers are from that day.

Written to be handed to a coding agent. §5 is the only slice that must ship for
the bug class to be closed; §7 and §8 are separable follow-ups.

---

## 0. Orientation — read these before writing code

- **The precedent this plan copies is `app/assets/substrate_crop.py`.** Read its
  module docstring first. Its whole thesis — "the fix is not linguistic:
  ... centre-crop it back to the style's exact canvas, in code, before anything
  is persisted" — is exactly this plan's thesis, applied to video instead of
  stills, with ffmpeg `cropdetect` instead of PIL.
- **The guard-band register to match is `app/renderer/parallax.py`.** Its
  `_KEY_SIMILARITY` / `_KEYED_FRACTION_MIN` / `_KEYED_FRACTION_MAX` constants
  are each a measured number with the measurement written beside them, and
  `check_keyed_fraction` / `check_keyed_distribution` are guards that refuse
  rather than degrade silently. Every constant §4 introduces must carry the
  same kind of comment.
- **This codebase documents WHY, heavily.** Comments record measured reasons,
  never what the code plainly does.
- There is no `CLAUDE.md`; learn conventions from neighbouring code.

### Constraints

- **Do not start a server.** The user runs their own.
- **Do not spend money.** No fal.ai, no ElevenLabs. Everything here is
  verifiable offline against files already on disk.
- Ad-hoc `pytest tests/unit` is safe. **Do not** run `make test` or seed with
  `--force` — both wipe the shared dev database.
- ffmpeg and ffprobe are installed and on PATH (`settings.ffmpeg_binary` /
  `settings.ffprobe_binary`).

---

## 1. The problem, measured

Project `2148489a-2171-4087-a29a-ec0b55b60525` ("Hycross killer?", 30 shots)
rendered several shots as a small picture marooned in the centre of a black
frame — "tunnel vision". Measured 2026-09-13 with `ffmpeg cropdetect` over all
21 `.mp4` assets in that project:

| Container | Real picture | `cropdetect` | Frame area that is dead black |
|---|---|---|---|
| 1920x1080 | 608x1080 | `crop=608:1080:656:0` | 68.3% |
| 1920x1080 | 608x1080 | `crop=608:1080:656:0` | 68.3% |
| 1920x1080 | 608x1080 | `crop=608:1080:656:0` | 68.3% |
| 1280x720 | 404x720 | `crop=404:720:438:0` | 68.4% |
| 1280x720 | 404x720 | `crop=404:720:438:0` | 68.4% |
| 16 others | full frame | `crop=` == full frame | 0% |

**5 of 21 (24%).** Each is a vertical phone clip that was exported or
downloaded into a LANDSCAPE container, with the pillarbox bars burned into the
pixels before the file ever reached this app. The detection was rock-stable:
for 4 of the 5, every sampled frame across the whole duration reported an
identical `crop=` box; the other varied by under 2% of frame height at one
transition.

**The 5th was found by the detector, not by the human pass.** The hand
diagnosis on 2026-09-13 tallied four, because two different files carry the
byte-identical `crop=404:720:438:0` signature and only one was counted. §9's
sweep over the same 21 files caught the missed one. Recorded here because it
is the argument for this plan existing at all: eyeballing `cropdetect` output
across a project is exactly the kind of tallying a human does slightly wrong,
and the whole point of §5 is that nobody ever has to do it again.

**68.4% is not an accident, and it is the number the guard band in §4 must
respect.** A 9:16 picture inside a 16:9 container occupies
`(9/16) / (16/9)` = 81/256 = 31.6% of the frame by construction, so a correct
detection on the single most common real case removes 68.4%. Any ceiling near
75% would sit only a few points above the ordinary case.

### Why it renders as tunnel vision

`app/renderer/slideshow.py` decides source framing in four places, and they
split into two families:

| Function | Lines | Fit mode | Used for |
|---|---|---|---|
| `_normalize_filter` | 312-332 | `decrease` + `pad` | STATIC / SPLIT_FRAME stills |
| `_motion_filter` | 473-496 | `decrease` + `pad` | MOTION clips |
| `_ken_burns_filter` | 499-536 | `increase` + `crop` | Ken-Burns zoom |
| `_ken_burns_pan_filter` | 539-610 | `increase` + `crop` | PAN |

The two `decrease` + `pad` paths are contain-fits:

```
scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2
```

A contain-fit is correct for a source whose whole frame is real picture. Given
a source that is 68% black bar, it faithfully scales the bars down along with
the picture and then pads the result — bars inside bars. A 1920x1080 source
contain-fit into 1080x1920 lands at 1080x607, of which only the middle 342px
is real picture: the measured artifact exactly.

The renderer is not wrong and should not be changed. It cannot distinguish
"black pixels that are a bar" from "black pixels that are night sky" — nothing
downstream of ingest can. **The only place that question can be answered is
once, at ingest, against the source file itself.**

---

## 2. What was already done by hand (do not redo)

On 2026-09-13 the 4 assets above were cropped to their real bounds, re-hashed,
renamed, and their `asset` rows updated (`content_hash`, `local_path`).
That project is fixed. The hand-fix needed the re-hash step because these
assets are content-addressable — the filename IS the sha256 of the bytes, and
`compute_render_fingerprint` reads `AssetModel.content_hash` from the DB
(via `_resolved_path_and_hash`, `app/workflow/steps/render.py:1438-1457`), so
correcting bytes without correcting the hash would have left every
fingerprint-keyed cache (`work_dir/shot_cache/{fp}.mp4`,
`work_dir/run_cache/{fp}.mp4`) happily serving the old bordered render.

**That whole dance is what this plan exists to make unnecessary.** Crop before
the hash is taken, and the hash is correct from birth.

---

## 3. Where video bytes enter the system

Verified 2026-09-14. Three, and only three, paths persist video bytes:

| # | Path | Where | Hash taken at |
|---|---|---|---|
| 1 | Provider / search download | `resolve_assets.py::_prefetch_search_rungs` | `hashlib.sha256(fetched.content)`, line 1697 |
| 2 | Human override upload | `projects.py::override_shot_asset` | `hashlib.sha256(content)`, line 2163 |
| 3 | Generated (fal.ai / Kling) | `resolve_assets.py::poll_video_job` | none — keyed by `prompt_hash`, line 918 |

`POST /{project_id}/assets` (`upload_assets`) is image-only — it calls
`validate_and_identify_image` with no video fallback, so a video uploaded there
is a 400 and it is not an ingest path.

**The ordering constraint is the whole design.** On path 1 the hash at line
1697 is computed from `fetched.content` before ranking, dedup
(`get_by_content_hash`) and the final `asset_repo.insert` all consume it. On
path 2 the same `content` local feeds two different writes — the clip write at
`projects.py:2127` and the asset write at line 2169. So on both paths the crop
must be applied to the bytes at the EARLIEST point they exist, not immediately
before a write; do it at a write and the hash no longer describes the file.

---

## 4. The new module: `app/assets/letterbox_crop.py`

One public function, shaped like `fit_upload_to_canvas` (always returns bytes;
"nothing to do" returns the input bytes unchanged):

```python
async def strip_baked_in_letterbox(
    video_bytes: bytes,
    *,
    ffmpeg_binary: str = "ffmpeg",
    ffprobe_binary: str = "ffprobe",
) -> bytes:
```

Bare-string defaults with `settings.*` threaded from the call site, matching
`validate_and_identify_video(content, ffprobe_binary=settings.ffprobe_binary)`
(`app/assets/validation.py:78-80`).

### Mechanism

1. Write bytes to a temp file and probe. Copy the idiom already in
   `app/assets/validation.py:103-106` verbatim, **including its
   `finally: tmp_path.unlink(missing_ok=True)` cleanup** (line 150-151) — that
   function solved this exact "arbitrary fetched bytes need a real file for
   ffprobe" problem first.
2. Sample `cropdetect` at ~5 evenly spaced timestamps, a fraction of a second
   each, rather than decoding the whole clip. Parse the LAST `crop=w:h:x:y`
   line emitted per sample (cropdetect converges as it accumulates frames).
3. Combine the samples by **union**, not by majority or by first: take
   `min(x1)`, `min(y1)`, `max(x2)`, `max(y2)` across samples. A real bar is
   identical in every sample, so the union costs nothing there — but if any one
   sampled instant happens to be a dark frame, the union refuses to crop away
   picture the other samples proved was real. Re-round the combined box to even
   `w`/`h`/`x`/`y` (h264 requires even dimensions; `cropdetect=round=2` only
   rounds each sample).

### The guard band

Constants live at module level with their measurement in the comment, exactly
as `parallax.py`'s do. The asymmetry that sets every threshold: **a missed
border is a cosmetic bug that a later re-run can still fix; a wrongly cropped
video is destroyed picture, because this runs before the original bytes are
ever persisted anywhere.** Every doubt resolves to "leave it alone."

- **Floor, ~2% of frame area.** Below this it is encoder edge noise or a
  one-pixel mastering artifact, not a bar worth a re-encode. (Real cases:
  68.4%.)
- **Ceiling, ~88% of frame area.** NOT 75%: §1 shows the canonical real case
  is 68.4%, and a 9:16-in-16:9 source is the commonest shape this will ever
  see, so a 75% ceiling leaves almost no headroom for a slightly wider bar or
  a marginally noisy read. 88% still catches the failure this ceiling is
  actually for — cropdetect on a near-black night shot returning a small
  bright island, which scores 95%+.
- **Aspect sanity.** Reject a resulting box whose aspect ratio is outside a
  generous band around real video shapes, and any box below a small absolute
  pixel floor. A plausible bar leaves a plausible frame.
- **Cross-sample stability.** If the union box is materially larger in area
  than the largest single-sample box, the dark region MOVED between samples —
  that is content, not a bar. Bail out. This is the strongest signal available
  and §1's measurement is what justifies leaning on it: real bars were
  pixel-identical across the entire duration in 3 of 4 files.
- **Any subprocess failure, timeout, or unparseable output → return the input
  bytes unchanged.** This deliberately does NOT follow `substrate_crop.py`'s
  raise-loudly contract. That function's precondition is the caller's to
  satisfy, so a violation is a caller bug worth surfacing. This function's job
  is opportunistic cleanup of arbitrary third-party video of unknown quality,
  where "could not tell" is an ordinary outcome. A human's upload must never
  fail because `cropdetect` had a bad day.
- **Log the decision either way** — cropped or not, the box, the fraction
  removed. This must not be invisible automation: the whole reason the original
  bug went unnoticed is that nothing ever said anything about source framing.

### The crop pass

If and only if the guard passes:

```
ffmpeg -i in.mp4 -vf crop=w:h:x:y -c:v libx264 -crf 16 -preset medium \
       -pix_fmt yuv420p -c:a copy out.mp4
```

`-crf 16` and `-c:a copy` are what the 2026-09-13 hand-fix used on all four
real files; the results were checked frame-by-frame against the originals and
were visually indistinguishable. Run it through `run_ffmpeg`
(`app/renderer/slideshow.py:208-219`) so it inherits the existing ffmpeg
concurrency semaphore rather than opening an unbounded second front.

---

## 5. Wiring — the slice that closes the bug class

Gate every call on `settings.letterbox_crop_enabled` (§6).

1. **`resolve_assets.py::_prefetch_search_rungs`**, between
   `fetched = await provider.fetch(candidate)` (line 1696) and
   `content_hash = hashlib.sha256(fetched.content).hexdigest()` (line 1697),
   when `candidate.media_kind == "video"`. `fetched.content` is read in exactly
   two places — that hash and the tuple appended on line 1699 — so correcting it
   here makes ranking, reuse-penalty tracking, dedup and insert all agree on one
   hash for the corrected bytes, with no other edit anywhere in the function.

2. **`projects.py::override_shot_asset`**, immediately after
   `media_type = "video"` is set (line 2021) — written as an `elif media_type ==
   "video":` sibling to the existing `if media_type == "image":`
   `fit_upload_to_canvas` block at line 2039, so the two media kinds get their
   respective ingest corrections in one obvious place. Placing it here (rather
   than before either write) is what makes it cover BOTH the clip write at line
   2127 and the asset write at line 2169, since both write the same `content`.

3. **`resolve_assets.py::poll_video_job`**, wrapping `status.content` before
   `path.write_bytes(...)` (lines 917-919). Lowest priority of the three — a
   model generating to a requested canvas is far less likely to emit bars than
   third-party footage is — but it is a two-line call and there is no hash
   ordering hazard at all here, since `prompt_hash` describes the REQUEST and
   never the output pixels.

---

## 6. Config

```python
letterbox_crop_enabled: bool = True
```

in `app/core/config.py`, matching the existing kill-switch convention
(`burn_captions` line 389, `loudness_normalize` line 402, `watermark_enabled`
line 428). `False` must make all three call sites byte-identical no-ops.

---

## 7. Tests — `backend/tests/unit/assets/test_letterbox_crop.py`

Follow `tests/unit/assets/test_substrate_crop.py`'s conventions: one test per
invariant, named for the invariant, each docstring saying why the test exists.

**Reuse the existing synthetic-clip builder** rather than inventing one:
`_make_real_clip` in `backend/tests/integration/test_motion_classification.py`
(lines 25-41) already builds a genuine decodable h264 clip via
`ffmpeg -f lavfi -i testsrc=duration=...:size=...:rate=24`. Generalise it (a
`pad=` on the lavfi source gives a clip with known bars) and lift it somewhere
both suites can import.

- `test_detects_and_crops_a_real_pillarbox` — known bars in, output dimensions
  exactly the true content box.
- `test_no_op_on_a_clip_with_no_border` — asserts the SAME BYTES return, not
  merely the same dimensions: 17 of 21 real assets are clean and must never pay
  a re-encode.
- `test_skips_a_trivial_border` — sub-floor border, no-op.
- `test_skips_when_the_dark_region_moves_between_samples` — content, not a bar;
  no-op. This is the false-positive case that matters most.
- `test_degrades_to_input_bytes_on_ffmpeg_failure` — truncated/corrupt input
  returns input, does not raise.
- `test_deterministic_same_bytes_same_output` — I5.
- `test_kill_switch_disables_every_call_site` — may live beside the call-site
  tests instead.

**Regression fixture:** the four real pre-crop originals from project
`2148489a` were backed up on 2026-09-13. Point the detector at them and assert
it independently arrives at `608:1080:656:0` and `404:720:438:0`. If those
backups have been swept, the current in-project files are the cropped versions
and re-padding one with ffmpeg reconstructs an equivalent fixture.

---

## 8. Separable follow-ups — do not block §5 on these

**8.1 Backfill — DECIDED AGAINST, 2026-09-14, by the user.** An earlier draft
of this plan proposed `backend/scripts/detect_letterboxed_assets.py` to sweep
every pre-existing project and repair bordered assets in place. The user
declined it outright: *"i dont want u to backfill anything, just that new
videos should not have this."* Recorded rather than deleted so it is not
re-proposed as an obvious missing piece.

The consequence, accepted knowingly: **assets ingested before §5 ships stay
bordered forever unless someone re-uploads them.** One such asset is known to
exist today — `c4ffd0c5…` in project `2148489a` (§1's fifth row), which will
keep rendering as tunnel vision. Anything else predating the fix is unaudited.
The remedy for any single case is a re-upload through the override endpoint,
which after §5 is cropped on the way in like any other new video.

**8.2 The same defect in still uploads.** `fit_upload_to_canvas` scales an
upload to COVER the canvas and centre-crops, so a bordered STILL does not
produce this exact artifact — the cover-crop may zoom past the bars, or into
them, depending on which axis is pinned. Different symptom, same root cause.
Worth hardening once the video path is proven, and cheaper there: PIL can scan
the boundary in-process, with no subprocess at all.

**8.3 Known gap, retroactive generated clips.** A `generated_clip` row is keyed
by `prompt_hash`, which describes the request, not the output pixels. §5.3
prevents the problem going forward, but if an ALREADY-generated clip ever needs
its bytes corrected in place, the fingerprint will not notice. The existing
precedent for solving that is `_file_sha256` (`app/workflow/steps/render.py:158-166`),
already used to fold real byte content into the fingerprint for layers for this
exact reason. Not needed unless a real case appears.

---

## 9. Verification

### Already run, 2026-09-14, against real files — §4's module passes

The module was built first and reviewed against the real corpus before any
call site was touched. Both sweeps are worth re-running after any change to
the guard band:

- **Reproduction.** Pointed at the five pre-crop originals, the detector
  independently arrived at `608x1080` (x3) and `404x720` (x2) — every box §1
  measured by hand, with nothing told to it.
- **False positives: zero.** Swept all 21 assets of project `2148489a`. The 16
  genuinely clean clips — which include dark car interiors and night driving
  footage, exactly the content a naive `cropdetect` mangles — all returned
  byte-identical input. The only clip cropped beyond the known set was the
  missed 5th, a true positive.
- **Idempotent.** The four already-cropped assets returned byte-identical too,
  so a clip that has already been through this is never re-encoded a second
  time — which matters because the override endpoint can receive the same
  clip twice.

### Still to run

- `pytest tests/unit/assets/test_letterbox_crop.py` — the §7 suite.
- Flip `letterbox_crop_enabled` to `False` and confirm all three call sites
  emit byte-identical results to today's behaviour.
- End to end, against the user's own running dev server: upload a clip with a
  known synthetic border through `POST /{project_id}/shots/{shot_id}/override`,
  then confirm on disk that the stored asset has no border AND that
  `sha256(file bytes) == asset.content_hash` — the invariant whose violation
  forced the manual DB repair in §2.
