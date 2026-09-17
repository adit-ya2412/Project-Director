/**
 * SPIKE — annotated stills (docs/plans/annotated_stills.md).
 *
 * Throwaway dev harness, NOT a production composition. It exists to
 * answer one question before any of N1-N12 is built: does
 * mark -> leader -> label, staged, on a static still, actually look
 * like something worth building?
 *
 * What is real here:
 *  - the picture is a real project asset
 *    (backend/storage/14191ca3-.../assets/a4199410...jpg)
 *  - annotation 1's coordinates are that asset's REAL focal sidecar
 *    value (focal_source="vision", 0.47, 0.31) — the Tier-1 path in
 *    §4 of the plan, which already ships
 *  - annotations 2 and 3 are hand-placed, standing in for Tier 3
 *    (`FOCAL_SOURCE_HUMAN`, the per-shot override that already exists)
 *
 * What is faked, and must not be mistaken for built:
 *  - label positions are hand-placed. In production K17
 *    (renderer/caption_placement.py) resolves the calmest free box.
 *  - the handwriting face is a SYSTEM font. compositor/src/font.ts
 *    records this codebase being bitten by exactly that; N6 vendors one.
 *  - nothing is props-driven; the real device is a cue on OverlayCue.
 */

import React from "react";
import {
  AbsoluteFill,
  Img,
  continueRender,
  delayRender,
  interpolate,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";

const MARK_COLOUR = "#FF2E2E";

/**
 * Kalam (SIL OFL), vendored into public/ for the spike. Chosen over
 * Architects Daughter / Patrick Hand / Permanent Marker / Caveat on one
 * hard fact, measured 2026-09-14 with fontTools: it is the ONLY
 * candidate carrying Devanagari (94 glyphs in U+0900-097F; every other
 * candidate has zero). This codebase burns Devanagari captions and
 * vendors NotoSansDevanagari; a Hindi label in any of the others would
 * be tofu.
 *
 * Loaded the same way font.ts loads the caption face — bundled, never
 * a system font and never a Google Fonts request. N6 moves this to
 * backend/vendor/fonts/ so libass and Remotion read one file.
 */
export const HAND = "KalamBundled";

const handle = delayRender("loading vendored Kalam");
const kalam = new FontFace(
  HAND,
  `url(${staticFile("Kalam-Regular.ttf")}) format("truetype")`,
);
kalam
  .load()
  .then((loaded) => {
    document.fonts.add(loaded);
    continueRender(handle);
  })
  .catch((err) => {
    console.error("Kalam failed to load", err);
    continueRender(handle);
  });

// Source asset's intrinsic size, needed to map normalised focal
// coordinates through the same cover-fit the renderer applies.
const SRC_W = 1200;
const SRC_H = 1808;

type Annotation = {
  /** Normalised into the SOURCE image, exactly like a focal sidecar. */
  x: number;
  y: number;
  rx: number;
  ry: number;
  label: string;
  /** Where the label sits, normalised into the source image. */
  lx: number;
  ly: number;
  align: "left" | "right";
  startFrame: number;
  seed: number;
};

const ANNOTATIONS: Annotation[] = [
  // Annotation 1 — the REAL focal sidecar value for this asset.
  // Note the sidecar's y=0.31 sits a little HIGH of the face centre
  // (~0.36). Kept unchanged: that is what vision actually returned, and
  // a spike that quietly corrects its own input proves nothing.
  {
    x: 0.47,
    y: 0.31,
    rx: 0.163,
    ry: 0.078,
    label: "focal · 0.47, 0.31",
    lx: 0.175,
    ly: 0.605,
    align: "left",
    startFrame: 22,
    seed: 7,
  },
  // Annotation 2 — hand-placed (Tier 3 stand-in).
  {
    x: 0.405,
    y: 0.115,
    rx: 0.088,
    ry: 0.064,
    label: "IPS cap badge",
    lx: 0.855,
    ly: 0.052,
    align: "right",
    startFrame: 112,
    seed: 21,
  },
  // Annotation 3 — hand-placed (Tier 3 stand-in).
  {
    x: 0.56,
    y: 0.793,
    rx: 0.232,
    ry: 0.05,
    label: "service ribbons",
    lx: 0.205,
    ly: 0.952,
    align: "left",
    startFrame: 200,
    seed: 43,
  },
];

/** Deterministic PRNG. Math.random() would re-jitter every frame and the
 *  circle would crawl — the mark must be identical on all 300 frames. */
export function mulberry32(seed: number) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/**
 * §5.4 — the mark should be imperfect. A geometrically perfect ellipse
 * reads as software; a stroke that wobbles and OVERSHOOTS its own start
 * reads as a human with a marker. `turns > 1` is the overshoot.
 */
export function wobblyEllipse(
  cx: number,
  cy: number,
  rx: number,
  ry: number,
  seed: number,
  turns = 1.14,
): string {
  const rand = mulberry32(seed);
  const steps = 64;
  const total = Math.PI * 2 * turns;
  // A slight tilt reads as hand-drawn far more than jitter alone does.
  const tilt = (rand() - 0.5) * 0.34;
  const pts: string[] = [];
  for (let i = 0; i <= steps; i++) {
    const t = (i / steps) * total - Math.PI * 0.6;
    const wobble = 1 + (rand() - 0.5) * 0.075;
    // Drift outward slightly as the stroke comes round, so the overshoot
    // sits just outside the start rather than retracing it.
    const drift = 1 + 0.05 * (i / steps);
    const ex = Math.cos(t) * rx * wobble * drift;
    const ey = Math.sin(t) * ry * wobble * drift;
    const px = cx + ex * Math.cos(tilt) - ey * Math.sin(tilt);
    const py = cy + ex * Math.sin(tilt) + ey * Math.cos(tilt);
    pts.push(`${i === 0 ? "M" : "L"}${px.toFixed(2)},${py.toFixed(2)}`);
  }
  return pts.join(" ");
}

export const AnnotationSpike: React.FC = () => {
  const frame = useCurrentFrame();
  const { width, height } = useVideoConfig();

  // The same cover-fit the renderer applies, so a normalised focal
  // coordinate lands where it lands in the delivered frame.
  const scale = Math.max(width / SRC_W, height / SRC_H);
  const dw = SRC_W * scale;
  const dh = SRC_H * scale;
  const offX = (width - dw) / 2;
  const offY = (height - dh) / 2;
  const toScreen = (nx: number, ny: number): [number, number] => [
    offX + nx * dw,
    offY + ny * dh,
  ];

  return (
    <AbsoluteFill style={{ backgroundColor: "#000" }}>
      {/* §5.1 — an annotated shot does NOT move. No Ken Burns here, and
          that is the point, not a shortcut. */}
      <Img
        src={staticFile("spike-subject.jpg")}
        style={{
          position: "absolute",
          left: offX,
          top: offY,
          width: dw,
          height: dh,
        }}
      />

      <svg
        width={width}
        height={height}
        style={{ position: "absolute", left: 0, top: 0 }}
      >
        {ANNOTATIONS.map((a, i) => {
          const local = frame - a.startFrame;
          if (local < 0) return null;

          // §5.2 — staged, never simultaneous. Mark, then line, then label.
          const markT = interpolate(local, [0, 13], [0, 1], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
          });
          const lineT = interpolate(local, [12, 30], [0, 1], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
          });
          const labelT = interpolate(local, [30, 38], [0, 1], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
          });

          const [cx, cy] = toScreen(a.x, a.y);
          const [lxRaw, ly] = toScreen(a.lx, a.ly);
          const rx = a.rx * dw;
          const ry = a.ry * dh;

          const path = wobblyEllipse(cx, cy, rx, ry, a.seed);

          // §5.3 — the line runs from the mark's edge to the label's
          // near end, and it is allowed to travel. No proximity bias.
          const labelEndX = lxRaw;
          const dx = labelEndX - cx;
          const dy = ly - cy;
          const mag = Math.hypot(dx, dy) || 1;
          const startX = cx + (dx / mag) * rx * 1.08;
          const startY = cy + (dy / mag) * ry * 1.08;
          const curX = startX + (labelEndX - startX) * lineT;
          const curY = startY + (ly - startY) * lineT;

          // Path length for the draw-on. Generous over-estimate is fine:
          // dashoffset only needs to exceed the true length.
          const markLen = (rx + ry) * 4;

          return (
            <g key={i}>
              <path
                d={path}
                fill="none"
                stroke={MARK_COLOUR}
                strokeWidth={5}
                strokeLinecap="round"
                strokeDasharray={markLen}
                strokeDashoffset={markLen * (1 - markT)}
                opacity={0.96}
              />
              {lineT > 0 && (
                <line
                  x1={startX}
                  y1={startY}
                  x2={curX}
                  y2={curY}
                  stroke={MARK_COLOUR}
                  strokeWidth={3.5}
                  strokeLinecap="round"
                  opacity={0.94}
                />
              )}
              {labelT > 0 && (
                <text
                  x={labelEndX + (a.align === "left" ? 10 : -10)}
                  y={ly + 2}
                  fill={MARK_COLOUR}
                  fontSize={34}
                  fontFamily={HAND}
                  textAnchor={a.align === "left" ? "start" : "end"}
                  dominantBaseline="middle"
                  opacity={labelT}
                  style={{
                    // A hair of rotation keeps it from reading as a caption.
                    transform: `translate(${(1 - labelT) * (a.align === "left" ? -10 : 10)}px, 0px) rotate(-1.2deg)`,
                    transformOrigin: `${labelEndX}px ${ly}px`,
                    paintOrder: "stroke",
                    stroke: "rgba(0,0,0,0.55)",
                    strokeWidth: 4,
                  }}
                >
                  {a.label}
                </text>
              )}
            </g>
          );
        })}
      </svg>
    </AbsoluteFill>
  );
};
