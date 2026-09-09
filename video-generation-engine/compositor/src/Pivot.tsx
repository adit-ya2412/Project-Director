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
 * rotate -1.5deg, band `#FF2E2E`, type white. Other canvases scale those
 * layout numbers; the shake formula is in frames and stays exact.
 */

const RED = "#FF2E2E";
const WHITE = "#FFFFFF";
const SPIKE_WIDTH = 720;
const SPIKE_HEIGHT = 1280;
const SPIKE_FONT = 132;
const SPIKE_TOP = 380;
const SPIKE_PAD = 18;

export type PivotProps = {
  text: string;
  startFrame: number;
  endFrame: number;
};

export const Pivot: React.FC<PivotProps> = ({ text, startFrame, endFrame }) => {
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

  const fontSize = Math.round(SPIKE_FONT * (width / SPIKE_WIDTH));
  const top = Math.round(SPIKE_TOP * (height / SPIKE_HEIGHT));
  const pad = Math.round(SPIKE_PAD * (height / SPIKE_HEIGHT));

  return (
    <div style={{ position: "absolute", top, left: 0, width, opacity: exit }}>
      <div
        style={{
          background: RED,
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
