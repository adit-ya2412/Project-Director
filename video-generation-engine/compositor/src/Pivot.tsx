import React from "react";
import {
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { DEVANAGARI } from "./font";

/**
 * The retention pivot — full-bleed red band, decaying shake, snap exit.
 *
 * Visual source of truth: the SUV spike (`SuvRetention.tsx` Beat 5,
 * 4.94–5.85s). Parameterized so production can drive it from `--props`
 * without generating a .tsx file per video. Do not "improve" this look.
 *
 * Spike numbers on a 720×1280 canvas: font 132, top 380, padding 18,
 * rotate -1.5deg, band `#FF2E2E`, type white. The shake formula is in
 * frames and stays exact.
 *
 * LAYOUT COMES FROM PROPS (review finding 3, 2026-09-09). This file used
 * to own its own copy of the layout constants while
 * `backend/app/renderer/emphasis_contrast.py` owned an identical copy,
 * used to decide WHERE on the plate to measure luma for K4's
 * light/dark/slab choice. Nothing tied the two together: moving the band
 * here left Python measuring the old rectangle and choosing a treatment
 * for a place the text is not — no exception, no failing test, just a
 * wrong answer. Python is now authoritative. It resolves the band
 * (`pivot_band` in `app/renderer/compositor.py`), measures that exact
 * rectangle, hashes it into the overlay cache and the render
 * fingerprint, and ships it here as `band`. Do not reintroduce layout
 * arithmetic in this component.
 *
 * The SPIKE_* constants below survive for ONE reason: the throwaway
 * standalone compositions (`SuvRetention.tsx`) render this component
 * with no `band`, and they are documented as spike code in
 * `compositor/README.md`. Production always passes `band` — see
 * `_overlay_props`. Nothing in the production path reads these.
 *
 * Hue: type stays white (K4 light on the band — the band IS the
 * ground). The band fill is K5 `pivotGround`, passed from Python.
 * `RED` below is a spike-only fallback for standalone compositions
 * that pass no palette; production always passes `pivotGround`.
 */

// FALLBACK ONLY — standalone spike compositions. Production passes `pivotGround`.
const RED = "#FF2E2E";
const WHITE = "#FFFFFF";
// FALLBACK ONLY — standalone spike compositions. See the note above.
const SPIKE_WIDTH = 720;
const SPIKE_HEIGHT = 1280;
const SPIKE_FONT = 132;
const SPIKE_TOP = 380;
const SPIKE_PAD = 18;

/**
 * The band rectangle, in canvas pixels, as Python resolved it.
 * Mirrors `PivotBand.as_props()`; `height` is intentionally absent —
 * the drawn height falls out of `fontSize`, `pad` and line-height, and
 * that docstring explains why the two are allowed to differ.
 */
export type PivotBandProps = {
  left: number;
  top: number;
  width: number;
  fontSize: number;
  pad: number;
};

export type PivotProps = {
  text: string;
  startFrame: number;
  endFrame: number;
  band?: PivotBandProps | null;
  // K5 pivot ground. Spike-only fallback is RED when missing.
  pivotGround?: string | null;
};

export const Pivot: React.FC<PivotProps> = ({
  text,
  startFrame,
  endFrame,
  band,
  pivotGround,
}) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const local = frame - startFrame;
  const visible = frame >= startFrame - 1 && frame <= endFrame;
  if (!visible) return null;

  const s = spring({
    frame: local,
    fps,
    config: { damping: 9, mass: 0.5, stiffness: 190 },
  });
  const bandW = interpolate(s, [0, 1], [0, 1]);
  // decaying shake — energy that dies out rather than a static hit
  const shake = Math.sin(local * 1.9) * Math.max(0, 10 - local * 1.6);
  // Retention style: exits are SNAPS, 3 frames. Nothing lingers.
  const exit = interpolate(frame, [endFrame - 3, endFrame], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  // Production: every one of these comes from Python's `pivot_band`, so
  // the drawn band and the measured band are the same numbers. The
  // `??` branches are the spike fallback and reproduce the identical
  // arithmetic Python performs, which is why the standalone
  // compositions look unchanged.
  const fontSize = band?.fontSize ?? Math.round(SPIKE_FONT * (width / SPIKE_WIDTH));
  const top = band?.top ?? Math.round(SPIKE_TOP * (height / SPIKE_HEIGHT));
  const pad = band?.pad ?? Math.round(SPIKE_PAD * (height / SPIKE_HEIGHT));
  const left = band?.left ?? 0;
  const bandWidth = band?.width ?? width;
  const ground = pivotGround ?? RED;

  return (
    <div
      style={{ position: "absolute", top, left, width: bandWidth, opacity: exit }}
    >
      <div
        style={{
          background: ground,
          padding: `${pad}px 0`,
          transform: `translateX(${shake}px) rotate(-1.5deg)`,
          clipPath: `inset(0 ${100 - bandW * 100}% 0 0)`,
          boxShadow: "0 12px 40px rgba(0,0,0,0.55)",
        }}
      >
        <div
          style={{
            textAlign: "center",
            fontFamily: `${DEVANAGARI}, sans-serif`,
            // Real Bold from the variable font's wght axis, NOT synthetic.
            // font.ts declares the 100-900 range so this instances the
            // font's own Bold master instead of smearing the matras.
            fontWeight: 700,
            fontSize,
            lineHeight: 1.1,
            color: WHITE,
          }}
        >
          {text}
        </div>
      </div>
    </div>
  );
};
