import React from "react";
import { AbsoluteFill } from "remotion";
import "./font";
import { Pivot } from "./Pivot";

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
  register: "hi" | "en";
  startFrame: number;
  endFrame: number;
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
          />
        );
      })}
    </AbsoluteFill>
  );
};
