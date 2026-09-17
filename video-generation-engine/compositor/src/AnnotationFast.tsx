/**
 * SPIKE 2 — the annotation device at `retention_fast` pace
 * (docs/plans/annotated_stills.md §5.7). Throwaway dev harness.
 *
 * The question this answers: a fast reel cuts at a 1.75s median with a
 * 3.5s ceiling. `AnnotationSpike`'s long-form reveal takes 1.27s before
 * a label is even readable. Does the device fit at all, and if so how?
 *
 * The answer built here is a COMPRESSED reveal, not a longer shot:
 *   mark 0.33s -> line 0.30s -> label 0.23s, overlapping, landed by
 *   ~0.97s, leaving ~0.9s of read time inside a 1.9s shot.
 *
 * Three real project assets, hard cuts, no motion (§5.1). Every mark
 * uses that asset's REAL vision focal sidecar value — so this also
 * shows what Tier 1 alone delivers across three different compositions,
 * warts included.
 */

import React from "react";
import {
  AbsoluteFill,
  Easing,
  Img,
  Sequence,
  interpolate,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { HAND, wobblyEllipse } from "./AnnotationSpike";

const MARK_COLOUR = "#FF2E2E";

/** Expo-out. Almost all of the travel happens in the first third, which
 *  is what makes a stroke read as struck rather than drawn. Linear
 *  interpolation was the single biggest reason v1 felt dull. */
const SNAP = Easing.bezier(0.16, 1, 0.3, 1);

/** 1.9s per shot at 30fps — just above retention_fast's 1.75s median
 *  and well under its 3.5s ceiling. */
const SHOT_FRAMES = 57;

type FastShot = {
  file: string;
  srcW: number;
  srcH: number;
  /** The asset's REAL focal sidecar value. */
  fx: number;
  fy: number;
  rx: number;
  ry: number;
  /** §5.7 — two words maximum. A fast reel has no time to read three. */
  label: string;
  /** Short form wants a SHORT line. §5.3's long lines are a long-form
   *  luxury: a line that travels costs frames the shot does not have. */
  lx: number;
  ly: number;
  align: "left" | "right";
  seed: number;
};

const SHOTS: FastShot[] = [
  {
    file: "fast-1.jpg",
    srcW: 3456,
    srcH: 4608,
    fx: 0.52,
    fy: 0.32,
    rx: 0.1,
    ry: 0.05,
    label: "parade drill",
    lx: 0.2,
    ly: 0.15,
    align: "left",
    seed: 11,
  },
  {
    file: "fast-2.png",
    srcW: 768,
    srcH: 1376,
    fx: 0.72,
    fy: 0.28,
    rx: 0.19,
    ry: 0.062,
    label: "live CCTV",
    lx: 0.3,
    ly: 0.44,
    align: "left",
    seed: 29,
  },
  {
    file: "fast-3.png",
    srcW: 768,
    srcH: 1376,
    fx: 0.62,
    fy: 0.49,
    rx: 0.17,
    ry: 0.058,
    label: "command desk",
    lx: 0.2,
    ly: 0.66,
    align: "left",
    seed: 53,
  },
];

const FastShotView: React.FC<{ shot: FastShot }> = ({ shot }) => {
  const frame = useCurrentFrame();
  const { width, height, fps } = useVideoConfig();

  const scale = Math.max(width / shot.srcW, height / shot.srcH);
  const dw = shot.srcW * scale;
  const dh = shot.srcH * scale;
  const offX = (width - dw) / 2;
  const offY = (height - dh) / 2;

  // v2 — PUNCH PASS (2026-09-14). v1 was correct and dull. Everything
  // below is about attack: expo-out easing, a spring on the label, an
  // impact pulse on the mark, and a slow push on the picture itself.

  // The mark is STRUCK, not drawn: 9 frames, almost all of it in the
  // first three.
  const markT = interpolate(frame, [3, 12], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: SNAP,
  });
  // Impact pulse the instant the stroke closes — this is the beat that
  // was missing entirely in v1.
  const pulse = interpolate(frame, [12, 16, 21], [1, 1.075, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.quad),
  });
  const line01 = interpolate(frame, [11, 19], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: SNAP,
  });
  // Spring, not a fade. Overshoots and settles — the label ARRIVES.
  const labelSpring = spring({
    frame: frame - 18,
    fps,
    config: { damping: 13, stiffness: 220, mass: 0.55 },
  });
  const labelT = interpolate(frame, [18, 22], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  // §5.1 REVISITED: the picture and the annotation are rendered in ONE
  // component here, so they can move together. A slow push costs
  // nothing and the shot stops feeling embalmed. This only works if
  // Remotion owns the picture for annotated shots — see the plan.
  const push = interpolate(frame, [0, SHOT_FRAMES], [1, 1.045], {
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.quad),
  });

  const cx = offX + shot.fx * dw;
  const cy = offY + shot.fy * dh;
  const lx = offX + shot.lx * dw;
  const ly = offY + shot.ly * dh;
  const rx = shot.rx * dw;
  const ry = shot.ry * dh;

  const path = wobblyEllipse(cx, cy, rx, ry, shot.seed);
  const markLen = (rx + ry) * 4;

  const dx = lx - cx;
  const dy = ly - cy;
  const mag = Math.hypot(dx, dy) || 1;
  const sx = cx + (dx / mag) * rx * 1.08;
  const sy = cy + (dy / mag) * ry * 1.08;

  // The label slides IN along the line's own direction, so it reads as
  // having been delivered by the line rather than appearing beside it.
  const slide = (1 - labelSpring) * 26;

  return (
    <AbsoluteFill style={{ backgroundColor: "#000", overflow: "hidden" }}>
      <AbsoluteFill style={{ transform: `scale(${push})` }}>
        <Img
          src={staticFile(shot.file)}
          style={{ position: "absolute", left: offX, top: offY, width: dw, height: dh }}
        />
        <svg width={width} height={height} style={{ position: "absolute", left: 0, top: 0 }}>
          <g transform={`translate(${cx} ${cy}) scale(${pulse}) translate(${-cx} ${-cy})`}>
            <path
              d={path}
              fill="none"
              stroke={MARK_COLOUR}
              strokeWidth={7}
              strokeLinecap="round"
              strokeDasharray={markLen}
              strokeDashoffset={markLen * (1 - markT)}
              opacity={0.97}
            />
          </g>
          {line01 > 0 && (
            <line
              x1={sx}
              y1={sy}
              x2={sx + (lx - sx) * line01}
              y2={sy + (ly - sy) * line01}
              stroke={MARK_COLOUR}
              strokeWidth={4.5}
              strokeLinecap="round"
              opacity={0.95}
            />
          )}
          {labelT > 0 && (
            <text
              x={lx + (shot.align === "left" ? 10 : -10)}
              y={ly + 2}
              fill={MARK_COLOUR}
              fontSize={40}
              fontFamily={HAND}
              textAnchor={shot.align === "left" ? "start" : "end"}
              dominantBaseline="middle"
              opacity={labelT}
              style={{
                transform: `translate(${shot.align === "left" ? -slide : slide}px, 0px) scale(${0.82 + 0.18 * labelSpring}) rotate(-1.2deg)`,
                transformOrigin: `${lx}px ${ly}px`,
                paintOrder: "stroke",
                stroke: "rgba(0,0,0,0.6)",
                strokeWidth: 5,
              }}
            >
              {shot.label}
            </text>
          )}
        </svg>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

export const AnnotationFast: React.FC = () => (
  <AbsoluteFill style={{ backgroundColor: "#000" }}>
    {SHOTS.map((shot, i) => (
      // Hard cuts only — retention_fast forbids dissolve and fade.
      <Sequence key={i} from={i * SHOT_FRAMES} durationInFrames={SHOT_FRAMES}>
        <FastShotView shot={shot} />
      </Sequence>
    ))}
  </AbsoluteFill>
);
