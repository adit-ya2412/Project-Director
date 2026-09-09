import React from "react";
import {
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { DEVANAGARI } from "./font";
import type { PivotBandProps } from "./Pivot";

/**
 * The retention stamp — one stressed word, punched on frame.
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
 * LAYOUT COMES FROM PROPS (review finding 3). Python resolves the box
 * (`stamp_band` in `app/renderer/compositor.py`), measures that exact
 * rectangle for K4, hashes it, and ships it here as `band`. The SPIKE_*
 * constants survive only as a fallback for standalone spike compositions
 * that pass no band; production always passes `band`.
 *
 * Latin faces: the spike used Segoe/Arial Black. No Latin file is
 * vendored (K6 is the Devanagari variable font only), so `en` keeps that
 * CSS stack. `hi` uses the bundled Noto so compositor faces never depend
 * on host fontconfig. Letter-spacing is 4px for Latin (Year) and 0 for
 * Devanagari — tracking Devanagari is the libass-breaking case.
 */

const WHITE = "#FFFFFF";
const INK = "#0A0A0B";
const AMBER = "#FFC300";
const HEAVY = "'Segoe UI Black','Arial Black',Impact,sans-serif";
const SHADOW = "0 6px 0 rgba(0,0,0,0.35), 0 0 26px rgba(0,0,0,0.6)";

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
};

export const Stamp: React.FC<StampProps> = ({
  text,
  textRegister,
  startFrame,
  endFrame,
  treatment,
  band,
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
  const clusters = graphemes(text, locale);
  const isHi = textRegister === "hi";
  const fontFamily = isHi ? `${DEVANAGARI}, sans-serif` : HEAVY;
  const letterSpacing = isHi ? 0 : 4;
  const typeColor = treatment === "dark" ? INK : WHITE;
  const textShadow = treatment === "light" ? SHADOW : "none";
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
            color: typeColor,
            letterSpacing,
            transform: `scale(${interpolate(s, [0, 1], [1.45, 1])})`,
            textShadow,
          }}
        >
          {clusters.map((g, i) => {
            const cs = spring({
              frame: local - i * 3,
              fps,
              config: { damping: 12, mass: 0.6, stiffness: 130 },
            });
            const y = interpolate(cs, [0, 1], [26, 0]);
            return (
              <span
                key={i}
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
        </div>
        <div
          style={{
            margin: "6px auto 0",
            width: ruleWidth,
            height: 10,
            background: AMBER,
            clipPath: `inset(0 ${50 - rule * 50}% 0 ${50 - rule * 50}%)`,
          }}
        />
      </div>
    </div>
  );
};
