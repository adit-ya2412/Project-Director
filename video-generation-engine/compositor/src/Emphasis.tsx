import React from "react";
import { AbsoluteFill } from "remotion";
import "./font";
import { Counter, type CounterValueProps } from "./Counter";
import { Pivot, type PivotBandProps } from "./Pivot";
import { Stamp } from "./Stamp";

/**
 * Production kinetic-text overlay. ONE composition driven by `--props`.
 * Do not generate a .tsx file per video (retention_fast_kinetic_text.md K7).
 *
 * Transparent fill — this is a LAYER; ffmpeg composites it with
 * `overlay=0:0:format=auto`. A default opaque fill would paint a black
 * rectangle over the plate.
 *
 * Renders `pivot`, `stamp`, and `counter`. Other devices in `cues` are
 * ignored (explicit default, not "only pivot exists") so later work can
 * extend the same props shape without a schema churn.
 */

export type EmphasisValueProps = CounterValueProps;

export type EmphasisCueProps = {
  device: string;
  text: string;
  textRegister: "hi" | "en";
  startFrame: number;
  endFrame: number;
  // K4: hashed into the overlay input so a treatment change misses
  // the compositor cache. Pivot drawing ignores this — the device IS
  // a slab (the red band). Stamp and counter branch on it.
  treatment: "light" | "dark" | "slab";
  // Review finding 3: the cue's band rectangle, resolved by Python
  // (`pivot_band` / `stamp_band` / `counter_band`), which is also the
  // rectangle K4 measured on the plate to pick `treatment` above.
  // Passing it means the treatment can no longer describe a region the
  // type does not cover. Nullable only when the canvas was degenerate.
  band?: PivotBandProps | null;
  // Counter target (value / unit / citedFragment). Empty for pivot and
  // stamp. citedFragment is not drawn; it is in the props so a citation
  // change misses the overlay cache.
  values?: EmphasisValueProps[];
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
        const key = `${cue.device}-${index}-${cue.startFrame}`;
        if (cue.device === "pivot") {
          return (
            <Pivot
              key={key}
              text={cue.text}
              startFrame={cue.startFrame}
              endFrame={cue.endFrame}
              band={cue.band}
            />
          );
        }
        if (cue.device === "stamp") {
          return (
            <Stamp
              key={key}
              text={cue.text}
              textRegister={cue.textRegister}
              startFrame={cue.startFrame}
              endFrame={cue.endFrame}
              treatment={cue.treatment}
              band={cue.band}
            />
          );
        }
        if (cue.device === "counter") {
          return (
            <Counter
              key={key}
              text={cue.text}
              textRegister={cue.textRegister}
              startFrame={cue.startFrame}
              endFrame={cue.endFrame}
              treatment={cue.treatment}
              band={cue.band}
              values={cue.values ?? []}
            />
          );
        }
        return null;
      })}
    </AbsoluteFill>
  );
};
