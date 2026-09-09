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
 * "The king of midsize SUV" (project fba52b6d, retention_fast, 720x1280)
 * — the first 7 seconds with NO captions, punctuated instead by kinetic
 * type. Captions transcribe; this PUNCTUATES.
 *
 * Real word onsets from that render's own ASS:
 *
 *   sadak 0.00  par 0.15  dikhne 0.26  wali 0.49
 *   har 0.69    teesri 0.83   SUV. 1.17 -> 1.49
 *   Hyundai 1.49  Creta 1.92  hai. 2.20 -> 2.69
 *   2025 2.69   mein 3.23  iske 3.36
 *   2 3.60      lakh 3.77  se 3.94  zyada 4.04  models 4.26  bike. -> 4.94
 *   lekin 4.94  kya 5.29   Creta 5.42
 *
 * "Every third SUV on the road is a Hyundai Creta. In 2025 over 2 lakh
 *  sold. But is the Creta really that special?"
 *
 * SAFE ZONES, read off the plate: the top ~200px carries shop signage
 * and the middle band is the car's grille — both busy. The clean bands
 * are y 250-460 (sky / roof) and y 900-1200 (road surface). Everything
 * below sits in one of those two.
 */

const AMBER = "#FFC300";
const WHITE = "#FFFFFF";
const RED = "#FF2E2E";
const INK = "#0A0A0B";

const HEAVY = "'Segoe UI Black','Arial Black',Impact,sans-serif";

const W = 720;

// ------------------------------------------------------------------ utils

const useWin = (inS: number, outS: number) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const inF = inS * fps;
  const outF = outS * fps;
  return {
    visible: frame >= inF - 1 && frame <= outF,
    local: frame - inF,
    fps,
    frame,
    // Retention style: exits are SNAPS, 3 frames. Nothing lingers.
    exit: interpolate(frame, [outF - 3, outF], [1, 0], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
    }),
  };
};

const drop = (local: number, fps: number, delay = 0, from = -140) => {
  const s = spring({
    frame: local - delay,
    fps,
    config: { damping: 11, mass: 0.5, stiffness: 150 },
  });
  return {
    y: interpolate(s, [0, 1], [from, 0]),
    scale: interpolate(s, [0, 1], [0.8, 1]),
    o: interpolate(s, [0, 0.3], [0, 1], { extrapolateRight: "clamp" }),
  };
};

const shadow = "0 6px 0 rgba(0,0,0,0.35), 0 0 26px rgba(0,0,0,0.6)";

// ----------------------------------- BEAT 1: word-by-word build (0.69-1.49)
// "EVERY / 3rd / SUV" — each word lands on its OWN onset. This is the
// build that captions cannot do, because a caption shows the whole line
// and only recolours the active word.

const Build: React.FC = () => {
  const { visible, local, exit, fps } = useWin(0.69, 1.49);
  if (!visible) return null;

  // delays in frames from 0.69s: har 0.69 (0), teesri 0.83 (+4), SUV 1.17 (+14)
  const a = drop(local, fps, 0, -90);
  const b = drop(local, fps, 4, -120);
  const c = drop(local, fps, 14, -160);

  return (
    <div style={{ position: "absolute", top: 300, left: 0, width: W, textAlign: "center", opacity: exit }}>
      <div
        style={{
          fontFamily: HEAVY,
          fontSize: 62,
          color: WHITE,
          letterSpacing: 8,
          opacity: a.o * 0.9,
          transform: `translateY(${a.y}px)`,
          textShadow: shadow,
        }}
      >
        EVERY
      </div>
      <div
        style={{
          fontFamily: HEAVY,
          fontSize: 168,
          lineHeight: 1,
          color: AMBER,
          opacity: b.o,
          transform: `translateY(${b.y}px) scale(${b.scale})`,
          textShadow: shadow,
        }}
      >
        3<span style={{ fontSize: 84 }}>rd</span>
      </div>
      <div
        style={{
          fontFamily: HEAVY,
          fontSize: 138,
          lineHeight: 1,
          color: WHITE,
          letterSpacing: 14,
          opacity: c.o,
          transform: `translateY(${c.y}px) scale(${c.scale})`,
          textShadow: shadow,
        }}
      >
        SUV
      </div>
    </div>
  );
};

// -------------------------------------- BEAT 2: brand lockup (1.49-2.60)
// A slab that WIPES open, then the name slams in on top of it. Slabs are
// how you get weight when the font has none to give.

const Brand: React.FC = () => {
  const { visible, local, exit, fps } = useWin(1.49, 2.6);
  if (!visible) return null;

  const slab = spring({ frame: local, fps, config: { damping: 200, mass: 0.4, stiffness: 150 } });
  const name = drop(local, fps, 3, -60);
  // "Creta" gets its own onset at 1.92 = +13 frames
  const creta = drop(local, fps, 13, 70);
  const tilt = interpolate(slab, [0, 1], [-4, -2]);

  return (
    <div style={{ position: "absolute", top: 330, left: 0, width: W, textAlign: "center", opacity: exit }}>
      <div style={{ display: "inline-block", transform: `rotate(${tilt}deg)` }}>
        <div
          style={{
            background: INK,
            padding: "10px 30px 14px",
            clipPath: `inset(0 ${100 - slab * 100}% 0 0)`,
          }}
        >
          <div
            style={{
              fontFamily: HEAVY,
              fontSize: 54,
              letterSpacing: 12,
              color: AMBER,
              opacity: name.o,
              transform: `translateY(${name.y * 0.3}px)`,
            }}
          >
            HYUNDAI
          </div>
          <div
            style={{
              fontFamily: HEAVY,
              fontSize: 132,
              lineHeight: 1,
              color: WHITE,
              letterSpacing: 2,
              opacity: creta.o,
              transform: `translateY(${creta.y}px) scale(${creta.scale})`,
            }}
          >
            CRETA
          </div>
        </div>
      </div>
    </div>
  );
};

// ------------------------------------------ BEAT 3: year stamp (2.69-3.55)

const Year: React.FC = () => {
  const { visible, local, exit, fps } = useWin(2.69, 3.55);
  if (!visible) return null;
  const s = spring({ frame: local, fps, config: { damping: 12, mass: 0.5, stiffness: 160 } });
  const rule = spring({ frame: local - 3, fps, config: { damping: 200, mass: 0.4 } });

  return (
    <div style={{ position: "absolute", top: 320, left: 0, width: W, textAlign: "center", opacity: exit }}>
      <div
        style={{
          fontFamily: HEAVY,
          fontSize: 190,
          lineHeight: 1,
          color: WHITE,
          letterSpacing: 4,
          transform: `scale(${interpolate(s, [0, 1], [1.45, 1])})`,
          opacity: interpolate(s, [0, 0.25], [0, 1], { extrapolateRight: "clamp" }),
          textShadow: shadow,
        }}
      >
        2025
      </div>
      <div
        style={{
          margin: "6px auto 0",
          width: 300,
          height: 10,
          background: AMBER,
          clipPath: `inset(0 ${50 - rule * 50}% 0 ${50 - rule * 50}%)`,
        }}
      />
    </div>
  );
};

// --------------------------------- BEAT 4: the counter (3.60-4.90)
// 0 -> 2,00,000 in Indian digit grouping, landing as "lakh" is spoken.
// The device that started this whole thread.

const Counter: React.FC = () => {
  const { visible, local, exit, fps } = useWin(3.6, 4.9);
  if (!visible) return null;

  const span = 0.95 * fps;
  const t = interpolate(local, [0, span], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });
  const value = Math.round(t * 200000);
  const s = spring({ frame: local, fps, config: { damping: 13, mass: 0.5, stiffness: 150 } });

  return (
    <div style={{ position: "absolute", top: 300, left: 0, width: W, textAlign: "center", opacity: exit }}>
      <div
        style={{
          fontFamily: HEAVY,
          fontSize: 116,
          lineHeight: 1,
          color: AMBER,
          fontVariantNumeric: "tabular-nums",
          transform: `scale(${interpolate(s, [0, 1], [0.7, 1])})`,
          textShadow: shadow,
        }}
      >
        {new Intl.NumberFormat("en-IN").format(value)}
        <span style={{ fontSize: 58, color: WHITE, marginLeft: 10 }}>+</span>
      </div>
      {/* meter: the same value again, as length */}
      <div style={{ margin: "16px auto 0", width: 420, height: 12, background: "rgba(0,0,0,0.45)" }}>
        <div style={{ width: `${t * 100}%`, height: "100%", background: AMBER }} />
      </div>
      <div
        style={{
          marginTop: 14,
          fontFamily: HEAVY,
          fontSize: 44,
          letterSpacing: 9,
          color: WHITE,
          opacity: 0.92,
          textShadow: shadow,
        }}
      >
        SOLD IN A YEAR
      </div>
    </div>
  );
};

// ------------------------------- BEAT 5: the pivot (4.94-5.85)
// "lekin" = "but". The turn is the single most important beat in a
// retention script, so it gets the loudest treatment in the reel: a
// full-bleed red band that slams in, with a shake that settles.

const Pivot: React.FC = () => {
  const { visible, local, exit, fps } = useWin(4.94, 5.85);
  if (!visible) return null;

  const s = spring({ frame: local, fps, config: { damping: 9, mass: 0.5, stiffness: 190 } });
  const bandW = interpolate(s, [0, 1], [0, 1]);
  // decaying shake — energy that dies out rather than a static hit
  const shake = Math.sin(local * 1.9) * Math.max(0, 10 - local * 1.6);

  return (
    <div style={{ position: "absolute", top: 380, left: 0, width: W, opacity: exit }}>
      <div
        style={{
          background: RED,
          padding: "18px 0",
          transform: `translateX(${shake}px) rotate(-1.5deg)`,
          clipPath: `inset(0 ${100 - bandW * 100}% 0 0)`,
          boxShadow: "0 12px 40px rgba(0,0,0,0.55)",
        }}
      >
        <div
          style={{
            textAlign: "center",
            fontFamily: `${DEVANAGARI}, sans-serif`,
            fontSize: 132,
            lineHeight: 1.1,
            color: WHITE,
          }}
        >
          लेकिन
        </div>
      </div>
    </div>
  );
};

// -------------------------------- BEAT 6: the question (5.42-7.0)
// Lands in the LOWER clean band (road surface) so it does not fight the
// pivot band above it — two elements, two zones.

const Question: React.FC = () => {
  const { visible, local, exit, fps } = useWin(5.42, 7.0);
  if (!visible) return null;
  const s = spring({ frame: local, fps, config: { damping: 12, mass: 0.5, stiffness: 150 } });
  const q = spring({ frame: local - 8, fps, config: { damping: 8, mass: 0.45, stiffness: 200 } });

  return (
    <div style={{ position: "absolute", top: 980, left: 0, width: W, textAlign: "center", opacity: exit }}>
      <div
        style={{
          fontFamily: HEAVY,
          fontSize: 96,
          lineHeight: 1,
          color: WHITE,
          letterSpacing: 4,
          opacity: interpolate(s, [0, 0.3], [0, 1], { extrapolateRight: "clamp" }),
          transform: `translateY(${interpolate(s, [0, 1], [60, 0])}px)`,
          textShadow: shadow,
        }}
      >
        REALLY
        <span
          style={{
            color: AMBER,
            display: "inline-block",
            marginLeft: 6,
            transform: `scale(${interpolate(q, [0, 1], [0.2, 1])}) rotate(${interpolate(q, [0, 1], [-25, 0])}deg)`,
          }}
        >
          ?
        </span>
      </div>
      <div
        style={{
          marginTop: 10,
          fontFamily: HEAVY,
          fontSize: 40,
          letterSpacing: 8,
          color: WHITE,
          opacity: 0.75 * interpolate(s, [0.3, 0.7], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }),
          textShadow: shadow,
        }}
      >
        THAT SPECIAL
      </div>
    </div>
  );
};

export const SuvRetention: React.FC = () => (
  <AbsoluteFill>
    <Build />
    <Brand />
    <Year />
    <Counter />
    <Pivot />
    <Question />
  </AbsoluteFill>
);
