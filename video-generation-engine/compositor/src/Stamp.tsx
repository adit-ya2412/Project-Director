import React from "react";
import {
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { DEVANAGARI } from "./font";
import type { PivotBandProps } from "./Pivot";
import { wordDelaySchedule } from "./stampWordTiming";

/**
 * The retention stamp — one stressed word, or a short phrase, punched
 * on frame.
 *
 * Visual source of truth: SUV spike Beat 3 (`SuvRetention.tsx` Year,
 * 2.69–3.55s) plus `EmphasisOverlay.tsx`'s per-cluster stagger. Do not
 * "improve" this look. Parameterized so production drives it from
 * `--props` without generating a .tsx file per video.
 *
 * Spike Year on 720×1280: font 190, top 320, full width, white type,
 * scale 1.45→1.0, amber rule 300×10 wiping open from centre. Production
 * adds grapheme-cluster stagger (never `.split("")` / `[...str]` — a
 * naive split orphans Devanagari matras) and branches on K4 `treatment`:
 * this is the first device that is NOT itself a slab.
 *
 * K14.5: a multi-word `text` (whitespace) staggers WORDS at spike-like
 * delays 0 / 4 / 14 / 24 frames; each word still grapheme-staggers
 * internally. A single word keeps today's grapheme-only path. Review
 * finding 3: those delays are now scheduled against the cue's actual
 * window (`endFrame - startFrame`) by `wordDelaySchedule`, so a 5th or
 * 6th word cannot be given an onset the hold never reaches. 1-3 words
 * at the pinned `STAMP_HOLD_S` are unchanged (0 / 4 / 14).
 *
 * LAYOUT COMES FROM PROPS (review finding 3). Python resolves the box
 * (`stamp_band` in `app/renderer/compositor.py`), measures that exact
 * rectangle for K4, hashes it, and ships it here as `band`. The SPIKE_*
 * constants survive only as a fallback for standalone spike compositions
 * that pass no band; production always passes `band`.
 *
 * K15: `band.fontSize` is therefore no longer one number per canvas —
 * Python measures the phrase and hands down the largest size that fits
 * on ONE line inside `band.width - 4 * pad`. A single word that fits at
 * the reference 190 is unchanged, which is the control the whole change
 * is checked against. This file adds `whiteSpace: nowrap` so a wrap
 * cannot happen even if that measurement is wrong; see the note at the
 * property.
 *
 * Latin faces: the spike used Segoe/Arial Black. No Latin file is
 * vendored (K6 is the Devanagari variable font only), so `en` keeps that
 * CSS stack. `hi` uses the bundled Noto so compositor faces never depend
 * on host fontconfig. Letter-spacing is 4px for Latin (Year) and 0 for
 * Devanagari — tracking Devanagari is the libass-breaking case.
 *
 * Hue: white `#FFFFFF` and ink `#0A0A0B` stay K4 literals. The rule
 * colour is K5 `accent`, passed from Python. `AMBER` below is a
 * spike-only fallback for standalone compositions that pass no palette;
 * production always passes `accent`.
 */

const WHITE = "#FFFFFF";
const INK = "#0A0A0B";
// FALLBACK ONLY — standalone spike compositions. Production passes `accent`.
const AMBER = "#FFC300";
const HEAVY = "'Segoe UI Black','Arial Black',Impact,sans-serif";
const SHADOW = "0 6px 0 rgba(0,0,0,0.35), 0 0 26px rgba(0,0,0,0.6)";
// The `dark` half of the same protection, added 2026-09-09. Until then
// `textShadow` was `treatment === "light" ? SHADOW : "none"`, which had
// it exactly backwards: `light` means the plate measured DARK, so white
// type already sits on a dark ground and a dark shadow adds almost
// nothing, while `dark` means the plate measured BRIGHT (the 236.9 SUV
// plate) and near-black type got NO protection at all — and a bright,
// UNEVEN plate is precisely where black type loses its edges. So `dark`
// gets a light halo, the analogue of what `light` gets. `slab` still
// needs neither: the device brings its own ground.
//
// Two glows and no offset ledge, unlike SHADOW: SHADOW is a hard 6px
// drop plus a wide blur, but offsetting a LIGHT halo under dark type
// would protect one side of each glyph and leave the other bare, and an
// uneven plate is uneven in no particular direction. Tight 10px at 0.95
// buys the edge separation, wide 26px at 0.8 lifts the surround.
// SHADOW itself is untouched — `light` was never the broken case.
const HALO = "0 0 10px rgba(255,255,255,0.95), 0 0 26px rgba(255,255,255,0.8)";

// FALLBACK ONLY — standalone spike compositions. See the note above.
const SPIKE_WIDTH = 720;
const SPIKE_HEIGHT = 1280;
const SPIKE_FONT = 190;
const SPIKE_TOP = 320;
const SPIKE_PAD = 14;
const SPIKE_RULE_WIDTH = 300;

const graphemes = (text: string, locale: string): string[] => {
  const Seg = (Intl as unknown as { Segmenter?: typeof Intl.Segmenter }).Segmenter;
  if (!Seg) return Array.from(text);
  const seg = new Seg(locale, { granularity: "grapheme" });
  return Array.from(seg.segment(text), (s: { segment: string }) => s.segment);
};

export type StampProps = {
  text: string;
  textRegister: "hi" | "en";
  startFrame: number;
  endFrame: number;
  treatment: "light" | "dark" | "slab";
  band?: PivotBandProps | null;
  // K5 accent. Spike-only fallback is AMBER when missing.
  accent?: string | null;
};

export const Stamp: React.FC<StampProps> = ({
  text,
  textRegister,
  startFrame,
  endFrame,
  treatment,
  band,
  accent,
}) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const local = frame - startFrame;
  const visible = frame >= startFrame - 1 && frame <= endFrame;
  if (!visible) return null;

  const s = spring({
    frame: local,
    fps,
    config: { damping: 12, mass: 0.5, stiffness: 160 },
  });
  const rule = spring({
    frame: local - 3,
    fps,
    config: { damping: 200, mass: 0.4 },
  });
  const slab = spring({
    frame: local,
    fps,
    config: { damping: 200, mass: 0.4, stiffness: 150 },
  });
  // Retention style: exits are SNAPS, 3 frames. Nothing lingers.
  const exit = interpolate(frame, [endFrame - 3, endFrame], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  const fontSize = band?.fontSize ?? Math.round(SPIKE_FONT * (width / SPIKE_WIDTH));
  const top = band?.top ?? Math.round(SPIKE_TOP * (height / SPIKE_HEIGHT));
  const pad = band?.pad ?? Math.round(SPIKE_PAD * (height / SPIKE_HEIGHT));
  const left = band?.left ?? 0;
  const bandWidth = band?.width ?? width;
  // 300/720 is the spike Year rule, expressed as a fraction of the
  // Python-owned band width so this file does not own a layout origin.
  const ruleWidth = Math.round(bandWidth * (SPIKE_RULE_WIDTH / SPIKE_WIDTH));

  const locale = textRegister === "hi" ? "hi" : "en";
  // K14.5: whitespace → word onsets; no whitespace → grapheme-only
  // (unchanged single-word path).
  const words = text.trim().length > 0 && /\s/.test(text) ? text.trim().split(/\s+/) : [text];
  // Review finding 3: the schedule is derived from the window this cue
  // was actually given, so no word is scheduled past the hold.
  const wordDelays = wordDelaySchedule(words.length, endFrame - startFrame);
  const isHi = textRegister === "hi";
  const fontFamily = isHi ? `${DEVANAGARI}, sans-serif` : HEAVY;
  const letterSpacing = isHi ? 0 : 4;
  const typeColor = treatment === "dark" ? INK : WHITE;
  const accentColor = accent ?? AMBER;
  // light -> dark plate -> white type + dark shadow.
  // dark  -> bright plate -> ink type + light halo (see HALO above).
  // slab  -> the device draws its own ground, so neither.
  const textShadow =
    treatment === "light" ? SHADOW : treatment === "dark" ? HALO : "none";
  const onSlab = treatment === "slab";

  return (
    <div
      style={{
        position: "absolute",
        top,
        left,
        width: bandWidth,
        textAlign: "center",
        opacity: exit,
      }}
    >
      <div
        style={{
          display: "inline-block",
          background: onSlab ? INK : "transparent",
          padding: onSlab ? `${pad}px ${pad * 2}px` : 0,
          clipPath: onSlab ? `inset(0 ${100 - slab * 100}% 0 0)` : undefined,
        }}
      >
        <div
          style={{
            fontFamily,
            fontWeight: isHi ? 700 : 900,
            fontSize,
            lineHeight: 1,
            // K15: A WRAP IS NEVER ACCEPTABLE HERE. Every grapheme
            // cluster below is its own `display:inline-block` span, and
            // CSS may break the line between inline-blocks — so the
            // U+00A0 joining the words was not protection at all, and a
            // phrase too wide for the band broke INSIDE a word:
            // `लाखों लोग` drew as `लाखों लो` / `ग`, splitting a cluster,
            // on 4 of the 8 cues of the 40.12s reel. `stamp_band` now
            // fits the font to one line, and this is the guarantee that
            // holds even when that measurement is wrong: too-small type
            // is a bad look, an orphaned syllable is a broken frame, so
            // the failure that survives is the harmless one (the line
            // overflows the slab and stays readable) rather than the
            // broken one.
            whiteSpace: "nowrap",
            color: typeColor,
            letterSpacing,
            transform: `scale(${interpolate(s, [0, 1], [1.45, 1])})`,
            textShadow,
          }}
        >
          {words.map((word, wi) => {
            const wordDelay = words.length > 1 ? (wordDelays[wi] ?? 0) : 0;
            const clusters = graphemes(word, locale);
            return (
              <span key={wi}>
                {wi > 0 ? "\u00A0" : null}
                {clusters.map((g, gi) => {
                  const cs = spring({
                    frame: local - wordDelay - gi * 3,
                    fps,
                    config: { damping: 12, mass: 0.6, stiffness: 130 },
                  });
                  const y = interpolate(cs, [0, 1], [26, 0]);
                  return (
                    <span
                      key={`${wi}-${gi}`}
                      style={{
                        display: "inline-block",
                        opacity: interpolate(cs, [0, 0.35], [0, 1], {
                          extrapolateRight: "clamp",
                        }),
                        transform: `translateY(${y}px)`,
                      }}
                    >
                      {g}
                    </span>
                  );
                })}
              </span>
            );
          })}
        </div>
        <div
          style={{
            margin: "6px auto 0",
            width: ruleWidth,
            height: 10,
            background: accentColor,
            clipPath: `inset(0 ${50 - rule * 50}% 0 ${50 - rule * 50}%)`,
          }}
        />
      </div>
    </div>
  );
};
