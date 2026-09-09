import React from "react";
import {
  Easing,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { DEVANAGARI } from "./font";
import type { PivotBandProps } from "./Pivot";

/**
 * The retention counter — a value counting to a stated number, plus meter.
 *
 * Visual source of truth: SUV spike Beat 4 (`SuvRetention.tsx` Counter,
 * 3.60–4.90s). Do not "improve" this look. Parameterized so production
 * drives it from `--props` without generating a .tsx file per video.
 *
 * Spike on 720×1280: top 300, font 116, amber tabular nums, Indian
 * grouping (`Intl.NumberFormat("en-IN")` → 2,00,000 not 200,000),
 * filling meter 420 wide, snap exit. Counts 0 → target over ~0.95 of
 * the hold, decelerating (`Easing.out(Easing.cubic)`), so it lands
 * before the window ends.
 *
 * A counter is Latin digits (role table). Unit tracking stays 0 so a
 * Devanagari unit suffix cannot be torn the way letter-spacing tore
 * matras in libass. The kicker is `text` when present — do not
 * hardcode "SOLD IN A YEAR".
 *
 * LAYOUT COMES FROM PROPS (review finding 3). Python resolves the box
 * (`counter_band`, centred, font 116). The slab/scrim draws that
 * rectangle; K4 measures it. Without a band K4 would use the frame
 * mean, a measured 54-luma loss of precision on the SUV reel.
 * SPIKE_* is a fallback for standalone compositions only.
 *
 * The band WIDTH is content-derived on the Python side as of 2026-09-09
 * (`max(420-scaled, digits + unit + 2*pad)`), because a hardcoded 420
 * was overrun by 59px of real type: `1,72,814+` at font 116 ran to
 * x=629 against a slab ending at x=570, measured on a render. Do not
 * compensate for that here — no `whiteSpace`, no `transform: scale`,
 * no shrink-to-fit. The band is the rectangle K4 measured for
 * `treatment` and the rectangle both hashes key on, so anything drawn
 * outside it is type whose contrast was never measured. If the type
 * still overflows, the estimate in `_counter_content_width` is wrong
 * and that is where it gets fixed.
 *
 * Latin faces: same CSS stack as the spike (no Latin file is vendored).
 * Hue: white `#FFFFFF` and ink `#0A0A0B` stay K4 literals. Digits and
 * the meter fill are K5 `accent`, passed from Python. `AMBER` below is
 * a spike-only fallback for standalone compositions that pass no
 * palette; production always passes `accent`. `onDark ? INK : accent`
 * is a K4 treatment branch, not a hue choice.
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
const SPIKE_FONT = 116;
const SPIKE_TOP = 300;
const SPIKE_PAD = 16;
const SPIKE_BAND_WIDTH = 420;

export type CounterValueProps = {
  value: number;
  unit: string | null;
  citedFragment: number;
};

export type CounterProps = {
  text: string;
  textRegister: "hi" | "en";
  startFrame: number;
  endFrame: number;
  treatment: "light" | "dark" | "slab";
  band?: PivotBandProps | null;
  values: CounterValueProps[];
  // K5 accent. Spike-only fallback is AMBER when missing.
  accent?: string | null;
};

export const Counter: React.FC<CounterProps> = ({
  text,
  textRegister,
  startFrame,
  endFrame,
  treatment,
  band,
  values,
  accent,
}) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const local = frame - startFrame;
  const visible = frame >= startFrame - 1 && frame <= endFrame;
  if (!visible) return null;

  const target = values[0]?.value ?? 0;
  const unit = values[0]?.unit ?? null;
  const spanFrames = Math.max(1, 0.95 * (endFrame - startFrame));
  const t = interpolate(local, [0, spanFrames], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });
  const value = Math.round(t * target);
  const s = spring({
    frame: local,
    fps,
    config: { damping: 13, mass: 0.5, stiffness: 150 },
  });
  const exit = interpolate(frame, [endFrame - 3, endFrame], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  const fontSize = band?.fontSize ?? Math.round(SPIKE_FONT * (width / SPIKE_WIDTH));
  const top = band?.top ?? Math.round(SPIKE_TOP * (height / SPIKE_HEIGHT));
  const pad = band?.pad ?? Math.round(SPIKE_PAD * (height / SPIKE_HEIGHT));
  const bandWidth =
    band?.width ?? Math.round(SPIKE_BAND_WIDTH * (width / SPIKE_WIDTH));
  const left = band?.left ?? Math.round((width - bandWidth) / 2);

  const isHi = textRegister === "hi";
  const kickerFamily = isHi ? `${DEVANAGARI}, sans-serif` : HEAVY;
  const onSlab = treatment === "slab";
  const onDark = treatment === "dark";
  const accentColor = accent ?? AMBER;
  // Accent is the watched number colour on dark plates / slabs; ink is
  // the contrast escape on a bright plate (the 4.3s infographic failure
  // was type with no ground of its own). K4 picks the branch; K5
  // supplies the hue.
  const numberColor = onDark ? INK : accentColor;
  const kickerColor = onDark ? INK : WHITE;
  // light -> dark plate -> white type + dark shadow.
  // dark  -> bright plate -> ink type + light halo (see HALO above).
  // slab  -> the device draws its own ground, so neither.
  const textShadow =
    treatment === "light" ? SHADOW : treatment === "dark" ? HALO : "none";

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
          background: onSlab ? "rgba(10,10,11,0.88)" : "transparent",
          padding: onSlab ? `${pad}px` : 0,
        }}
      >
        <div
          style={{
            fontFamily: HEAVY,
            fontSize,
            lineHeight: 1,
            color: numberColor,
            fontVariantNumeric: "tabular-nums",
            transform: `scale(${interpolate(s, [0, 1], [0.7, 1])})`,
            textShadow,
          }}
        >
          {new Intl.NumberFormat("en-IN").format(value)}
          {unit ? (
            <span
              style={{
                fontSize: Math.round(fontSize * 0.5),
                color: kickerColor,
                marginLeft: 10,
                letterSpacing: 0,
                fontFamily: kickerFamily,
                fontWeight: isHi ? 700 : 900,
              }}
            >
              {unit}
            </span>
          ) : null}
        </div>
        <div
          style={{
            margin: `${pad}px auto 0`,
            width: "100%",
            height: 12,
            background: "rgba(0,0,0,0.45)",
          }}
        >
          <div style={{ width: `${t * 100}%`, height: "100%", background: accentColor }} />
        </div>
        {text ? (
          <div
            style={{
              marginTop: 14,
              fontFamily: kickerFamily,
              fontWeight: isHi ? 700 : 900,
              fontSize: Math.round(fontSize * (44 / 116)),
              letterSpacing: isHi ? 0 : 9,
              color: kickerColor,
              opacity: 0.92,
              textShadow,
            }}
          >
            {text}
          </div>
        ) : null}
      </div>
    </div>
  );
};
