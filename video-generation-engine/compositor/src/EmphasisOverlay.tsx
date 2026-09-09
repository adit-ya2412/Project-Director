import React from "react";
import { DEVANAGARI } from "./font";
import {
  AbsoluteFill,
  Easing,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";

/**
 * V2 spike — the emphasis stamp, built to do specifically what ASS cannot.
 *
 * Timings are the REAL ElevenLabs character-level onsets from
 * project 3ad7d0ca, scene act_01_sc_01:
 *
 *   "इतिहास का सबसे बड़ा झूठ, जो दो हज़ार सालों तक सच माना गया।"
 *
 *   झूठ            1.52 -> 2.64s   (held 1.12s, ~4x the line average)
 *   दो हज़ार सालों   2.88 -> 3.87s
 *
 * Vertical placement is 168px, not centre: that shot already carries a
 * `text_card` mid-frame plus the channel watermark top-right, which the
 * V1 test surfaced by colliding with both.
 */

const STAMP_IN_S = 1.52;
const STAMP_OUT_S = 2.64;
const COUNT_IN_S = 2.88;
const COUNT_OUT_S = 3.87;

const STAMP_Y = 168;
const WARM_WHITE = "#E8F6FF";

/**
 * Split for per-character stagger by GRAPHEME CLUSTER, never by code point.
 *
 * This is the whole reason the stagger is safe on Devanagari. "झूठ" is
 * three code points — झ + ू + ठ — but only TWO clusters, because ू is a
 * combining vowel sign that belongs to झ. Naive [...str] or .split("")
 * would tear ू off its base and animate it as an orphan, which is
 * exactly the dotted-circle failure the libass V1 attempt produced for a
 * different reason (letter-spacing).
 */
const graphemes = (text: string, locale = "hi"): string[] => {
  const Seg = (Intl as unknown as { Segmenter?: typeof Intl.Segmenter }).Segmenter;
  if (!Seg) return Array.from(text);
  const seg = new Seg(locale, { granularity: "grapheme" });
  return Array.from(seg.segment(text), (s: { segment: string }) => s.segment);
};

type StampProps = {
  text: string;
  kicker?: string;
  locale?: string;
  /** letter-spacing in px — the case that BROKE Devanagari in libass */
  tracking?: number;
};

/** A word that springs in per-cluster, with a rule that draws under it. */
const Stamp: React.FC<StampProps> = ({ text, kicker, locale = "hi", tracking = 0 }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const inFrame = STAMP_IN_S * fps;
  const outFrame = STAMP_OUT_S * fps;
  const local = frame - inFrame;

  if (frame < inFrame - 1 || frame > outFrame) return null;

  // Hard-ish exit: 5 frames. A slow fade-out reads as timid.
  const exit = interpolate(frame, [outFrame - 5, outFrame], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  const clusters = graphemes(text, locale);

  // The rule under the word WIPES open via clipPath — a mask, not a fade.
  const ruleReveal = spring({
    frame: local - 4,
    fps,
    config: { damping: 200, mass: 0.5, stiffness: 90 },
  });

  return (
    <div
      style={{
        position: "absolute",
        top: STAMP_Y,
        left: 0,
        right: 0,
        textAlign: "center",
        opacity: exit,
      }}
    >
      <div
        style={{
          fontFamily: `${DEVANAGARI}, sans-serif`,
          fontSize: 124,
          fontWeight: 400,
          color: WARM_WHITE,
          letterSpacing: tracking,
          lineHeight: 1.15,
          // Two shadows: a tight dark edge for legibility on any image,
          // plus a soft drop so it sits above the photograph.
          textShadow:
            "0 2px 0 rgba(16,16,16,0.9), 0 0 18px rgba(0,0,0,0.75), 0 10px 34px rgba(0,0,0,0.55)",
        }}
      >
        {clusters.map((g, i) => {
          // Each cluster gets its own spring, delayed 3 frames.
          // damping 12 + mass 0.6 gives real overshoot — the thing two
          // chained linear \t tags in ASS can only approximate.
          const s = spring({
            frame: local - i * 3,
            fps,
            config: { damping: 12, mass: 0.6, stiffness: 130 },
          });
          const scale = interpolate(s, [0, 1], [0.55, 1]);
          const y = interpolate(s, [0, 1], [26, 0]);
          return (
            <span
              key={i}
              style={{
                display: "inline-block",
                opacity: interpolate(s, [0, 0.35], [0, 1], {
                  extrapolateRight: "clamp",
                }),
                transform: `translateY(${y}px) scale(${scale})`,
              }}
            >
              {g}
            </span>
          );
        })}
      </div>

      {/* The rule: a real mask reveal, opening from the centre outward. */}
      <div
        style={{
          margin: "10px auto 0",
          width: 260,
          height: 3,
          background: WARM_WHITE,
          opacity: 0.85,
          clipPath: `inset(0 ${50 - ruleReveal * 50}% 0 ${50 - ruleReveal * 50}%)`,
        }}
      />

      {kicker ? (
        <div
          style={{
            marginTop: 14,
            fontFamily: "'Noto Sans', sans-serif",
            fontSize: 34,
            fontWeight: 600,
            letterSpacing: 8,
            color: WARM_WHITE,
            opacity: interpolate(local, [6, 16], [0, 0.62], {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
            }),
            textShadow: "0 0 14px rgba(0,0,0,0.85)",
          }}
        >
          {kicker}
        </div>
      ) : null}
    </div>
  );
};

/**
 * The headline item: a number that COUNTS UP across the spoken window.
 * ASS interpolates transforms, never text content, so this is the one
 * element in the test that the current stack structurally cannot produce.
 */
const Counter: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const inFrame = COUNT_IN_S * fps;
  const outFrame = COUNT_OUT_S * fps;
  if (frame < inFrame - 1 || frame > outFrame) return null;

  const local = frame - inFrame;
  const span = (outFrame - inFrame) * 0.72; // land before the word ends

  // Decelerating count, so it settles on 2,000 rather than stopping dead.
  const value = Math.round(
    interpolate(local, [0, span], [0, 2000], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
      easing: Easing.out(Easing.cubic),
    })
  );

  const enter = spring({
    frame: local,
    fps,
    config: { damping: 14, mass: 0.6, stiffness: 120 },
  });
  const exit = interpolate(frame, [outFrame - 5, outFrame], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <div
      style={{
        position: "absolute",
        top: STAMP_Y,
        left: 0,
        right: 0,
        textAlign: "center",
        opacity: exit,
      }}
    >
      <div
        style={{
          fontFamily: `${DEVANAGARI}, sans-serif`,
          fontSize: 124,
          fontWeight: 400,
          color: WARM_WHITE,
          transform: `scale(${interpolate(enter, [0, 1], [0.6, 1])})`,
          textShadow:
            "0 2px 0 rgba(16,16,16,0.9), 0 0 18px rgba(0,0,0,0.75), 0 10px 34px rgba(0,0,0,0.55)",
          // Tabular figures so the digits do not jitter while counting.
          fontVariantNumeric: "tabular-nums",
        }}
      >
        {new Intl.NumberFormat("en-IN").format(value)}
        <span style={{ fontSize: 62, marginLeft: 18, opacity: 0.92 }}>साल</span>
      </div>
    </div>
  );
};

export type OverlayProps = {
  /** "hi" renders झूठ, "en" renders LIE — testing which register reads better */
  variant?: "hi" | "en";
  /** apply letter-spacing to the stamp (the libass-breaking case) */
  tracking?: number;
};

export const EmphasisOverlay: React.FC<OverlayProps> = ({
  variant = "hi",
  tracking = 0,
}) => {
  // No background colour anywhere: this composition renders as alpha and
  // is composited over the existing shot by FFmpeg, so the pipeline keeps
  // its master clock and its assembler. Remotion is a LAYER PRODUCER here,
  // not a replacement renderer.
  return (
    <AbsoluteFill>
      {variant === "hi" ? (
        <Stamp text="झूठ" kicker="A LIE" locale="hi" tracking={tracking} />
      ) : (
        <Stamp text="LIE" locale="en" tracking={tracking} />
      )}
      <Counter />
    </AbsoluteFill>
  );
};
