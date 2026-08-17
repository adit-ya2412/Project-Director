# Watermark / Channel Branding — Implementation Plan

> **Status:** Built and verified, 2026-08-17. See **§10 Implementation log** for what shipped, what was decided, and how it was verified.
> **Expands:** [`ffmpeg_watermark_addition.md`](ffmpeg_watermark_addition.md) (the original sketch).
> **Fixture:** project `71e4758a-1a05-4a47-982b-c97861777d20` — already rendered, already has `renders/final.mp4`.

---

## Verdict up front

**The watermark itself is genuinely short work — about one day.** The sketch is right that it needs no changes to the timeline, scene, shot, or asset pipeline. It is a rendering-layer feature and nothing above the renderer has to know it exists.

**But one line in the sketch is not short work.** The output matrix at the bottom —

```
├── YouTube version   → watermark ON
├── Instagram version → watermark ON
└── Archive version   → watermark OFF
```

— is a **separate, much larger feature** than the watermark filter, and it is the part that touches the data model. See §7. Everything else here assumes one output per project, as today.

---

## 1. The one architectural decision that matters

`RenderStep` currently runs a **four-stage pass chain** (`app/workflow/steps/render.py`), and the important property is which stages re-encode video:

| Stage | Output | Video |
|---|---|---|
| `render_timeline` | `silent_path` | encoded (composition, Ken Burns, crossfades) |
| **captions** | `captioned_path` | **RE-ENCODED** — `subtitles=` cannot run through `-c:v copy` |
| `mux_narration` | `narrated_path` | stream-copied |
| `mux_music` | `output_path` | stream-copied |

The caption pass is deliberately the **only** video re-encode after composition, and its own comment explains the sequencing: it runs early, on the smaller silent file, precisely so the two muxing passes downstream can stream-copy instead of forcing a second encode.

**An `overlay` filter also cannot stream-copy.** So the obvious implementation — "add a watermark pass at the end" — would introduce a **second full re-encode** of the finished video. That costs encode time on every render and, worse, imposes a second generation of lossy compression on material that has already been through x264 once.

**Therefore: the watermark belongs in the same FFmpeg invocation as captions**, as one filter chain (`subtitles=…,overlay=…`), not as its own pass. One re-encode, exactly as now.

This has a direct consequence for the code: the existing pass is gated on `caption_cues is None`, and it must instead be gated on **captions OR watermark being enabled**. Rename it accordingly — it stops being "the caption pass" and becomes "the video filter pass". `captions.py::burn_captions` generalises to take a filter chain rather than assuming `subtitles=` alone.

---

## 2. What captions already solved, and this simply copies

Commit `9ab51bd` built captions end to end, and it established every pattern this feature needs. That is why the estimate is a day and not three:

- **Vendored binary asset + content hash.** `FONT_DIR = .../vendor/fonts`, with `caption_font_content_hash()` hashing the actual file. The logo does exactly this: `vendor/branding/`, hashed by content. Vendoring (rather than an arbitrary filesystem path from config) is what keeps I5 true — the render depends on a file in the repo we can hash, not on whatever happens to exist on that machine.
- **FFmpeg filter path escaping.** `escape_ffmpeg_filter_path()` already handles the Windows drive-letter colon trap (`C\:/path/x.ass`). The overlay's input path needs the same treatment; the function exists.
- **Fingerprint discipline.** Captions added `burn_captions` / `caption_font_hash` / `cue_list_hash`, following the "always present, `None` when moot" rule that `music_content_hash` set. §4 mirrors it.
- **The draft carve-out.** `RenderSettings.burn_captions` defaults to `False` so drafts never burn captions regardless of config. Same treatment for the watermark (§5).

---

## 3. Filter construction

Build the chain in `app/renderer/` next to the caption helpers, as a pure string-producing function — no I/O, no config reads — so it is testable without rendering anything.

Three FFmpeg concerns, in order:

1. **Scale the logo relative to frame width**, never in absolute pixels, so the same branding is proportionally identical at draft and final resolution. The sketch's `width_percent` is the right idea.
2. **Apply opacity.** A PNG's own alpha is multiplied by the configured opacity — in practice `format=rgba,colorchannelmixer=aa=<opacity>` on the logo input before overlaying.
3. **Position from a named corner plus a margin**, resolved into `overlay=x=…:y=…` expressions using `main_w`/`main_h`/`overlay_w`/`overlay_h` so it is resolution-independent. Support the four corners; that covers every real branding need.

**A note on the sketch's numbers:** `width_percent: 4` on a 720-wide frame is a **28-pixel** logo inside a 1280-tall video. That is very likely too small to read on a phone. Typical channel bugs sit around 8–12% of frame width. Worth looking at a real frame before settling — which is cheap, because §6's fixture gives you one immediately.

---

## 4. Fingerprint — non-negotiable

`compute_render_fingerprint` decides whether to skip a render entirely and serve the existing file. **Every input that changes output bytes must be in it.** This is the R2 lesson, and captions already took it seriously.

Add, following the established shape:

- `watermark_enabled: bool` — always present
- `watermark_asset_hash: str | None` — the **logo file's content hash**, not its path, so replacing the logo invalidates the cache
- `watermark_params_hash: str | None` — position, margin, opacity and width percent folded into one value

`None` when the watermark is off, mirroring `caption_font_hash`. Make them **required kwargs**, as R2 forced for the music gains — that is the mechanism that stops the next such input being forgotten silently.

Skip this and the failure is the exact R2 signature: **you change the logo, re-render, and get the old video back**, byte-identical and wrong, with no error anywhere.

---

## 5. Drafts

**Recommend: no watermark on drafts**, mirroring captions. `RenderSettings.watermark: bool = False` by default, set true only on the final path.

Drafts exist for pacing and asset checks at 480p in seconds. Branding is a publish concern. And the draft/final fingerprints already differ by resolution, so nothing collides either way.

---

## 6. Testing with `71e4758a`

This fixture is well suited to the watermark specifically — better than it was for captions — because **the watermark's correctness is almost entirely visual and resolution-relative**, and this project is already fully rendered.

- **Filter-string unit tests.** All four corner positions, margin and opacity arithmetic, and path escaping — pure functions, no FFmpeg, no database.
- **Fingerprint tests.** Watermark on vs off produce different fingerprints; changing the logo file changes the fingerprint; changing only opacity changes the fingerprint. These are the tests that would have caught R2.
- **Determinism.** Same input, byte-identical output twice, watermark on. `tests/integration/test_render_determinism.py` is the existing proof harness and must stay green.
- **Real render against the fixture** — 6 scenes, 19 shots, 58.3s, already has narration and music, so it exercises the full four-stage chain rather than a synthetic one-shot timeline. Confirm by ffprobe that the output still has exactly one video stream at the right resolution and that duration is unchanged.
- **Look at an actual frame.** Extract a frame and check the logo is where it should be, legible, and not covering a caption. No assertion catches "the branding sits on top of the subtitles" — and with captions now shipping, that collision is a real risk worth checking once by eye (§8.3).

> ⚠ **Before running the suite: export the fixture.** `pytest` truncates the shared Postgres, which deletes every real project in it — `71e4758a` included. `backend/scripts/export_test_project.py` writes it to `tests/fixtures/` so it survives. A live project was lost to exactly this once already. And never run two `pytest` processes at once.

---

## 7. The output matrix is a different feature — do not fold it in

The sketch's three-variant list looks like a small addition and is not. Today:

- `project.video_path` is a **single** nullable string (`app/models/project.py`).
- `GET /{id}/video` serves that one file.
- `render` rows are keyed by fingerprint, so the table *could* hold several outputs per project — but nothing above it can express "which one".

Producing YouTube / Instagram / Archive variants therefore needs: a way to name and address variants, a `video_path` that is no longer one path, API changes to select one, retention rules per variant, and a fingerprint that already distinguishes them (it would, via `watermark_enabled` — that part is free).

**Recommendation: build the watermark now against the existing single-output model, and treat variants as a separate piece of work with its own plan.** They compose cleanly later precisely because the fingerprint already separates a watermarked render from an unwatermarked one. Nothing here forecloses it.

Worth asking first, though: is the archive-without-branding case actually needed today, or is it speculative? If nobody has asked for a clean master yet, the whole matrix may be a solution to a problem you do not have — and the single-output path stays much simpler.

---

## 8. Open questions

1. **Is the branding asset per-project or global?** The sketch implies one channel logo, which means global config plus a vendored file — simplest, and what §2 assumes. If different projects need different logos it becomes project state, and then it is an I2 decision belonging on the Timeline, not config.
2. **What is the actual logo file?** Nothing exists at `branding/logo.png` today. Needs a real transparent PNG at enough resolution to scale down cleanly — supply the asset before building, since §6's visual check is meaningless without it.
3. **Watermark and captions can collide.** Captions now ship, positioned above the platform-UI band at the bottom of frame. A `bottom_right` watermark with a 40px margin may land on top of them. Either choose a corner captions never occupy (top-right is the conventional channel-bug position and is free), or make the caption safe-area explicit so both can be positioned against it.
4. **Static image only, or animated?** This plan assumes a static PNG. An animated or video watermark is a different filter graph and materially more work.

---

## 9. Effort

**~1 day**, assuming the logo asset exists and §8 is settled:

- Filter construction + unit tests: ~3 hours
- Folding into the caption pass and generalising it (§1): ~2 hours
- Fingerprint wiring + tests: ~2 hours
- Config, vendored asset, draft carve-out: ~1 hour
- Real render against `71e4758a` and the visual check: ~1 hour

The estimate holds **only** because captions already built the vendoring, escaping, fingerprint and draft-carve-out patterns this copies. Had this been attempted before `9ab51bd`, it would have been the two-to-three-day job of establishing all of them from scratch.

Excluded from the estimate: the output matrix (§7), which is a separate feature.

---

## 10. Implementation log (2026-08-17)

### 10.1 §8's open questions, as answered

1. **Asset scope:** global, one vendored logo — confirmed, matches §2's assumption.
2. **The logo file:** provided — a real RGBA PNG, 1254×1254, genuine alpha transparency (0–255 range, not a flat channel). Downscaled to 512×512 (447KB, down from 2.5MB — no reason to vendor a 1254px source for something that renders at ~50–200px) and vendored at `backend/vendor/branding/logo.png`.
   - **Worth flagging, not a blocker:** this is a dense, detailed circular channel badge (fine wordmark, small subtext, several small illustrative elements) — the kind of asset designed to be viewed large, like a channel avatar, not a small always-on corner bug. At ~10% frame width the fine detail and subtext will likely wash out; only the "PAST THE SURFACE" wordmark silhouette is expected to read. Not fixed here — resolved empirically in §10.4's real-frame check rather than assumed.
3. **Position:** top-right, confirmed — avoids the caption safe-zone entirely (captions occupy the bottom of frame, above the platform-UI band).
4. **Static vs animated:** static PNG only, confirmed — matches §3/§8.4's assumption, no change needed.
5. **Output scope (§7):** confirmed single-output only. The archive-without-branding case was confirmed speculative, not a current need — the multi-output matrix stays a separate, deferred future plan.
6. **Sizing default:** 10% width (vs. the sketch's 4%) and a proportional margin (3% of frame width, not the sketch's absolute `40px` — margins as absolute pixels would silently mean something different at draft vs. final resolution; kept as a fraction for the same reason width already was, even though drafts never get the watermark today).

### 10.2 Architecture, as actually built

Per §1, generalized rather than added-as-a-second-pass:

- **`app/renderer/video_filters.py`** (new) — owns `escape_ffmpeg_filter_path` (moved out of `captions.py`, no longer caption-specific) and `apply_video_filters(video_path, output_path, settings, *, extra_inputs, filter_complex, output_label)`, the one ffmpeg invocation both captions and the watermark now share. Neither `captions.py` nor `watermark.py` runs ffmpeg itself any more — each only builds a `filter_complex` **fragment** referencing an input/output label.
- **`app/renderer/captions.py`** — `burn_captions` (the old standalone pass) replaced by `subtitles_filter_fragment(input_label, output_label, ass_path, font_dir) -> str`, a pure string builder.
- **`app/renderer/watermark.py`** (new) — `LOGO_PATH` (resolved from the module's own location, mirroring `FONT_DIR`), `watermark_content_hash()`, `watermark_params_hash(...)`, and `watermark_filter_fragment(input_label, output_label, logo_input_index, *, frame_width, position, width_fraction, margin_fraction, opacity) -> str`.
- **Composition in `render.py`:** a running `(current_label, extra_inputs)` pair — starts at `"0:v"` with no extra inputs; captions (if on) append a fragment and advance the label to `"captioned"`; the watermark (if on) appends the logo as an extra input, appends its own fragment referencing whatever the current label is, and advances to `"watermarked"`. If neither ran, the silent file is renamed directly (unchanged behavior for the current no-captions-no-watermark case). This is what makes captions-only, watermark-only, both, or neither all resolve to exactly one or zero re-encodes, never two.
- **Position math:** the logo's target width and the margin are resolved to concrete pixel values in Python from the render's known width (`round(frame_width * fraction)`) — the same pattern `serialize_ass` already used for caption font size/margin, not a live ffmpeg `main_w` expression. Positioning WITHIN the frame (which corner) does use ffmpeg's own `main_w`/`main_h`/`overlay_w`/`overlay_h` expressions, since the scaled logo's exact height depends on its aspect ratio after `scale=W:-1`, which only ffmpeg knows without redundantly re-deriving it in Python.
- **Config:** `watermark_enabled` (default `False` — unlike `burn_captions`, this flips on live behavior the moment it's true, so it doesn't start pre-enabled), `watermark_position`, `watermark_width_fraction` (0.10), `watermark_margin_fraction` (0.03), `watermark_opacity` (0.65).
- **`RenderSettings.watermark_enabled`** — same per-call-site carve-out as `burn_captions`: the draft endpoint omits it (defaults `False`), `RenderStep` passes `settings.watermark_enabled`.
- **Fingerprint:** `watermark_enabled`/`watermark_asset_hash`/`watermark_params_hash` added as required kwargs, `None` when off — the exact R2/caption pattern, documented inline in `fingerprint.py`.

### 10.3 Tests, as actually written

- `tests/unit/renderer/test_watermark.py` — filter fragment construction (all four corners, width/margin arithmetic, opacity, logo-input-index referencing, unknown-position error), content hash correctness, params hash sensitivity to each parameter independently.
- `tests/unit/renderer/test_video_filters.py` — the relocated path-escaping tests.
- `tests/unit/renderer/test_fingerprint.py` — extended with `watermark_enabled` toggle, asset-hash, and params-hash cases, mirroring the existing caption ones exactly.
- `tests/integration/test_render_watermark_determinism.py` (new) — byte-identical-twice with the watermark alone, AND with captions+watermark composed in the same pass (proving the one-re-encode composition actually works against real ffmpeg, not just in the abstract).
- `tests/integration/test_render_captions_determinism.py` — updated in place (it imported the now-removed `burn_captions`; now builds its fragment via `subtitles_filter_fragment` + `apply_video_filters`, same behavior).
- Full regression sweep after the refactor: 285 unit tests (was 269 before this feature) and the render-related integration/e2e suite, both passing — confirms the `captions.py`/`render.py` refactor didn't regress the captions feature it grew out of.

### 10.4 Real-render / visual verification — done

Rendered two width variants (10% and 15%) against the real fixture `71e4758a` — full 58.3s composition, real captions burned in, real narration audio muxed on, using the actual on-disk assets (no DB, no synthetic data). Frames pulled at multiple points, over both a plain poster background and a dense text-heavy background.

**Result:** at 10% the logo's wordmark was borderline legible, as flagged in §10.1. At **15%** the "PAST THE SURFACE" wordmark reads clearly on both backgrounds, without the badge dominating the frame or looking oversized. Zero caption collision at either size, at any of the sampled timestamps — top-right and the bottom caption position never come close to overlapping, confirming §8 point 3's concern doesn't materialise in practice, not just by construction.

**Decided: `watermark_width_fraction = 0.15`**, not the plan's originally-recommended 0.10 — set as the config default, confirmed by the user against the real rendered frames rather than assumed. Position (top-right), margin (3%), and opacity (0.65) all held at their originally-recommended values; only width changed.

This closes out the plan. Remaining open item, unchanged from §7: the output matrix (YouTube/Instagram watermarked, Archive clean) stays deferred, its own future plan.
