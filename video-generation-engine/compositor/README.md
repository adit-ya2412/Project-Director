# compositor

Remotion layer producer for the kinetic-text system. Promoted out of a
throwaway spike on 2026-09-09 after the plan's gate passed
(`docs/plans/retention_fast_kinetic_text.md`).

**Status: SPIKE CODE, kept because it runs.** These compositions are the
proof, not the design. `SuvRetention.tsx` and `DirectedHook.tsx` hardcode
one film's word onsets — they exist so K7 starts from something that
renders rather than from prose. The production shape is ONE parameterised
composition driven by `--props`; see the plan's "K7 — the compositor
seam, specified".

## What is worth keeping from each file

- `font.ts` — the `delayRender` font-loading pattern. Loads the VENDORED
  `NotoSansDevanagari-Regular.ttf`, not a system or Google font, for the
  same reason `captions.py` passes libass an explicit `fontsdir=`. Only
  Nirmala.ttc exists system-wide on Windows, so a CSS request for "Noto
  Sans Devanagari" silently falls back to a different typeface than the
  captions use. Keep this pattern; vendor a Bold weight (K6).
- `EmphasisOverlay.tsx` — grapheme-cluster stagger via `Intl.Segmenter`,
  and the tracked-Devanagari variant that proved Chromium shapes what
  libass could not.
- `DirectedHook.tsx` — the correction device (strike wipes, does not
  fade) and the counter+meter pair. Note the 48% strike position and why.
- `SuvRetention.tsx` — the retention vocabulary: word-by-word build,
  slab lockup, Indian-grouped counter, full-bleed pivot band, decaying
  shake.

## Run

```
npm install
npx remotion studio
npx remotion render SuvRetention out/overlay.mov \
  --codec=prores --prores-profile=4444 \
  --pixel-format=yuva444p10le --image-format=png
```

Composite over a plate with ffmpeg — Remotion produces a LAYER, ffmpeg
stays the assembler:

```
ffmpeg -i plate.mp4 -i out/overlay.mov \
  -filter_complex "[0:v][1:v]overlay=0:0:format=auto,format=yuv420p[v]" \
  -map "[v]" -map 0:a -c:a copy composited.mp4
```

Requires Node 18+ (verified on v22.15.1). Chrome Headless Shell
downloads itself into `node_modules` on first render.
