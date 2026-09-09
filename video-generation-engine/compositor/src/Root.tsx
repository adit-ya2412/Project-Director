import React from "react";
import { Composition } from "remotion";
import { EmphasisOverlay } from "./EmphasisOverlay";
import { DirectedHook } from "./DirectedHook";
import { SuvRetention } from "./SuvRetention";

// 7.2s at 30fps = 216 frames, matching the V0/V1 test clip exactly.
export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id="Emphasis-hi"
        component={EmphasisOverlay}
        durationInFrames={216}
        fps={30}
        width={1280}
        height={720}
        defaultProps={{ variant: "hi" as const, tracking: 0 }}
      />
      <Composition
        id="Emphasis-en"
        component={EmphasisOverlay}
        durationInFrames={216}
        fps={30}
        width={1280}
        height={720}
        defaultProps={{ variant: "en" as const, tracking: 0 }}
      />
      {/* The libass-breaking case: tracked Devanagari. Does Chromium shape it? */}
      <Composition
        id="Emphasis-hi-tracked"
        component={EmphasisOverlay}
        durationInFrames={216}
        fps={30}
        width={1280}
        height={720}
        defaultProps={{ variant: "hi" as const, tracking: 14 }}
      />
      <Composition
        id="DirectedHook"
        component={DirectedHook}
        durationInFrames={216}
        fps={30}
        width={1280}
        height={720}
      />
      <Composition
        id="SuvRetention"
        component={SuvRetention}
        durationInFrames={210}
        fps={30}
        width={720}
        height={1280}
      />
    </>
  );
};
