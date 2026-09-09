import React from "react";
import { AbsoluteFill } from "remotion";
import "./font";
import { Pivot, type PivotBandProps } from "./Pivot";

/**
 * Production kinetic-text overlay. ONE composition driven by `--props`.
 * Do not generate a .tsx file per video (retention_fast_kinetic_text.md K7).
 *
 * Transparent fill — this is a LAYER; ffmpeg composites it with
 * `overlay=0:0:format=auto`. A default opaque fill would paint a black
 * rectangle over the plate.
 *
 * This slice renders `pivot` only. Other devices in `cues` are ignored
 * so later work can extend the same props shape without a schema churn.
 */

export type EmphasisCueProps = {
  device: string;
  text: string;
  textRegister: "hi" | "en";
  startFrame: number;
  endFrame: number;
  // K4: hashed into the overlay input so a treatment change misses
  // the compositor cache. Pivot drawing ignores this — the device IS
  // a slab (the red band). Later devices (stamp) will branch on it.
  treatment: "light" | "dark" | "slab";
  // Review finding 3: the cue's band rectangle, resolved by Python
  // (`pivot_band`), which is also the rectangle K4 measured on the
  // plate to pick `treatment` above. Passing it means the treatment
  // can no longer describe a region the band does not cover. Nullable
  // only for devices that have no band yet; pivot always has one.
  band?: PivotBandProps | null;
};

export type EmphasisProps = {
  canvas: { width: number; height: number };
  fps: number;
  durationInFrames: number;
  cues: EmphasisCueProps[];
};

export const DEFAULT_EMPHASIS_PROPS: EmphasisProps = {
  canvas: { width: 720, height: 1280 },
  fps: 30,
  durationInFrames: 1,
  cues: [],
};

export const Emphasis: React.FC<EmphasisProps> = ({ cues }) => {
  return (
    <AbsoluteFill style={{ backgroundColor: "transparent" }}>
      {cues.map((cue, index) => {
        if (cue.device !== "pivot") return null;
        return (
          <Pivot
            key={`${cue.device}-${index}-${cue.startFrame}`}
            text={cue.text}
            startFrame={cue.startFrame}
            endFrame={cue.endFrame}
            band={cue.band}
          />
        );
      })}
    </AbsoluteFill>
  );
};
