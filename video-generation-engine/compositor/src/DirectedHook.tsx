import React from "react";
import {
  AbsoluteFill,
  Easing,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { DEVANAGARI } from "./font";

/**
 * The first 7.2s of `plato uncovered`, DIRECTED — four devices from the
 * same family as the counter, each locked to a real ElevenLabs onset.
 *
 * Real word timings (project 3ad7d0ca, scene act_01_sc_01):
 *
 *   इतिहास  0.00  का 0.56  सबसे 0.82  बड़ा 1.25
 *   झूठ,    1.52 -> 2.64   <- held 1.12s, the stress of the line
 *   जो      2.64
 *   दो 2.88  हज़ार 3.04  सालों 3.44 -> 3.87
 *   तक      3.87
 *   सच      4.19 -> 4.44   <- "believed TRUE"
 *   माना    4.44
 *   गया।    4.77 -> 6.12   <- held 1.35s, the sentence lands
 *   दुनिया   6.12 -> 6.80
 *
 * All four devices share one mechanic: a value or state that CHANGES
 * across a spoken window. That is what ASS cannot express — it can move
 * and scale a finished string, never alter what the string says.
 */

const WARM = "#E8F6FF";
const RED = "#E2564A";
const TOP = 168;

// ---------------------------------------------------------------- utils

const graphemes = (text: string, locale = "hi"): string[] => {
  const Seg = (Intl as unknown as { Segmenter?: typeof Intl.Segmenter }).Segmenter;
  if (!Seg) return Array.from(text);
  return Array.from(new Seg(locale, { granularity: "grapheme" }).segment(text), (s: {
    segment: string;
  }) => s.segment);
};

const useWindow = (inS: number, outS: number) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const inF = inS * fps;
  const outF = outS * fps;
  const visible = frame >= inF - 1 && frame <= outF;
  const local = frame - inF;
  const exit = interpolate(frame, [outF - 5, outF], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  return { visible, local, exit, fps };
};

const shadow =
  "0 2px 0 rgba(16,16,16,0.9), 0 0 18px rgba(0,0,0,0.75), 0 10px 34px rgba(0,0,0,0.55)";

// ------------------------------------------------- 1. the stamp (झूठ)

const Stamp: React.FC = () => {
  const { visible, local, exit, fps } = useWindow(1.52, 2.6);
  if (!visible) return null;
  const clusters = graphemes("झूठ");
  const rule = spring({ frame: local - 4, fps, config: { damping: 200, mass: 0.5 } });

  return (
    <div style={{ position: "absolute", top: TOP, left: 0, right: 0, textAlign: "center", opacity: exit }}>
      <div style={{ fontFamily: `${DEVANAGARI}, sans-serif`, fontSize: 132, color: WARM, textShadow: shadow }}>
        {clusters.map((g, i) => {
          const s = spring({ frame: local - i * 3, fps, config: { damping: 12, mass: 0.6, stiffness: 130 } });
          return (
            <span
              key={i}
              style={{
                display: "inline-block",
                opacity: interpolate(s, [0, 0.35], [0, 1], { extrapolateRight: "clamp" }),
                transform: `translateY(${interpolate(s, [0, 1], [26, 0])}px) scale(${interpolate(s, [0, 1], [0.55, 1])})`,
              }}
            >
              {g}
            </span>
          );
        })}
      </div>
      <div
        style={{
          margin: "12px auto 0",
          width: 300,
          height: 3,
          background: WARM,
          opacity: 0.85,
          clipPath: `inset(0 ${50 - rule * 50}% 0 ${50 - rule * 50}%)`,
        }}
      />
    </div>
  );
};

// ------------------------- 2. the counter + 3. a meter filling under it

const CounterWithMeter: React.FC = () => {
  const { visible, local, exit, fps } = useWindow(2.88, 3.87);
  if (!visible) return null;

  const span = (3.87 - 2.88) * fps * 0.72;
  const t = interpolate(local, [0, span], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });
  const value = Math.round(t * 2000);
  const enter = spring({ frame: local, fps, config: { damping: 14, mass: 0.6 } });

  return (
    <div style={{ position: "absolute", top: TOP, left: 0, right: 0, textAlign: "center", opacity: exit }}>
      <div
        style={{
          fontFamily: `${DEVANAGARI}, sans-serif`,
          fontSize: 132,
          color: WARM,
          textShadow: shadow,
          fontVariantNumeric: "tabular-nums",
          transform: `scale(${interpolate(enter, [0, 1], [0.6, 1])})`,
        }}
      >
        {new Intl.NumberFormat("en-IN").format(value)}
        <span style={{ fontSize: 62, marginLeft: 16, opacity: 0.92 }}>साल</span>
      </div>

      {/* DEVICE 3 — a meter. The same value, shown a second way: a bar
          filling as the number climbs. Two readings of one quantity is a
          classic explainer move and costs nothing once the value exists. */}
      <div style={{ margin: "14px auto 0", width: 360, height: 6, background: "rgba(255,255,255,0.18)", borderRadius: 3 }}>
        <div style={{ width: `${t * 100}%`, height: "100%", background: WARM, borderRadius: 3, boxShadow: "0 0 12px rgba(232,246,255,0.6)" }} />
      </div>
    </div>
  );
};

// --------------------------- 4. the correction (strike-through + replace)

/**
 * The device that fits this film's whole thesis: a claim appears, a line
 * draws through it, and the truth replaces it.
 *
 * "सच" is on screen from 4.19s (the narrator says "believed TRUE"). The
 * strike draws 4.55 -> 4.90. The correction lands at 5.00.
 *
 * Note the strike is a WIPE (clipPath), not a fade — the line travels,
 * which is what makes it read as an act of correction rather than a
 * decoration appearing.
 */
const Correction: React.FC = () => {
  const { visible, local, exit, fps } = useWindow(4.19, 6.05);
  if (!visible) return null;

  const strike = interpolate(local, [0.36 * fps, 0.71 * fps], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.inOut(Easing.quad),
  });
  const fade = interpolate(strike, [0.5, 1], [1, 0.32], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const truth = spring({ frame: local - 0.81 * fps, fps, config: { damping: 13, mass: 0.6, stiffness: 130 } });

  return (
    <div
      style={{
        position: "absolute",
        top: TOP,
        left: 0,
        right: 0,
        textAlign: "center",
        opacity: exit,
      }}
    >
      {/* One LINE, not a stack. Two reasons: a correction reads better as
          "claim -> truth" left to right, and stacking put the replacement
          straight on top of the shot's own text_card, where both became
          unreadable. The frame has horizontal room it does not have
          vertical room. */}
      <div style={{ display: "inline-flex", alignItems: "center", gap: 26 }}>
        <span style={{ position: "relative", display: "inline-block" }}>
          <span
            style={{
              fontFamily: `${DEVANAGARI}, sans-serif`,
              fontSize: 100,
              color: WARM,
              opacity: fade,
              textShadow: shadow,
            }}
          >
            सच
          </span>
          {/* Strike sits at 48%, not 56%: Devanagari carries its visual
              mass high under the shirorekha, so a Latin-centred strike
              reads as an underline instead of a cancellation. */}
          <span
            style={{
              position: "absolute",
              left: -12,
              right: -12,
              top: "48%",
              height: 8,
              background: RED,
              borderRadius: 4,
              clipPath: `inset(0 ${100 - strike * 100}% 0 0)`,
              boxShadow: "0 0 14px rgba(226,86,74,0.7)",
            }}
          />
        </span>

        <span
          style={{
            fontFamily: `${DEVANAGARI}, sans-serif`,
            fontSize: 62,
            color: WARM,
            opacity: interpolate(truth, [0, 0.4], [0, 0.75], { extrapolateRight: "clamp" }),
            textShadow: shadow,
          }}
        >
          &#8594;
        </span>

        <span
          style={{
            fontFamily: `${DEVANAGARI}, sans-serif`,
            fontSize: 100,
            color: WARM,
            textShadow: shadow,
            opacity: interpolate(truth, [0, 0.4], [0, 1], { extrapolateRight: "clamp" }),
            transform: `translateY(${interpolate(truth, [0, 1], [18, 0])}px) scale(${interpolate(truth, [0, 1], [0.72, 1])})`,
            display: "inline-block",
          }}
        >
          झूठ
        </span>
      </div>
    </div>
  );
};

export const DirectedHook: React.FC = () => (
  <AbsoluteFill>
    <Stamp />
    <CounterWithMeter />
    <Correction />
  </AbsoluteFill>
);
