Yes — better to keep it as **one architecture/scope document** for now.

Create/replace:

```text
docs/CINEMATIC_RENDERING.md
```

````md
# Cinematic Rendering & Composition

## 1. Purpose

Extend the video engine from a basic media assembler into a programmable documentary composition engine.

The current renderer already supports:

- Video clips
- Images
- Zoom and pan
- Voiceover
- BGM
- Audio ducking
- SFX
- Timeline assembly
- Captions
- Watermarks

The cinematic rendering layer will add higher-level visual direction while keeping the existing timeline and orchestration architecture intact.

The goal is not to simply add more effects.

The goal is to give the AI a vocabulary of cinematography and allow the renderer to execute that direction.

---

# 2. Current Pipeline

```text
Script
  ↓
Director
  ↓
Timeline
  ↓
Scenes
  ↓
Shots
  ↓
Assets
  ↓
Voice + BGM + SFX
  ↓
FFmpeg Renderer
  ↓
Final Video
````

---

# 3. Target Pipeline

```text
Script
  ↓
Director
  ↓
Timeline
  ↓
Scenes
  ↓
Shots
  ↓
Shot Direction
  ↓
Asset Selection
  ↓
Shot Composition
  ↓
Scene Assembly
  ↓
Audio Mix
  ↓
Final Render
```

---

# 4. Core Concept

A shot should contain more than:

```text
asset + duration
```

A shot should eventually contain:

```text
asset
duration
shot type
camera movement
movement intensity
focus
depth
composition
text
transition
mood
audio synchronization
```

Example:

```json
{
  "asset": "victorian_portrait.jpg",
  "duration": 5,
  "camera": {
    "movement": "push_in",
    "intensity": 0.35,
    "easing": "cinematic"
  },
  "composition": {
    "depth": "subtle_parallax",
    "focus": "face"
  },
  "text": null,
  "transition": {
    "type": "crossfade",
    "duration": 0.4
  }
}
```

The Director describes what the shot should communicate.

The Renderer decides how to execute it.

---

# 5. Cinematography Vocabulary

## 5.1 Shot Types

The Director may eventually choose:

* Wide
* Medium
* Close-up
* Extreme close-up
* Detail
* Establishing shot

---

## 5.2 Camera Movement

Supported movement primitives:

* Static
* Push in
* Pull out
* Pan left
* Pan right
* Tilt up
* Tilt down
* Tracking
* Slow drift

Movement intensity:

```text
0.0 → Static
0.25 → Subtle
0.5 → Moderate
0.75 → Strong
1.0 → Aggressive
```

Documentary content should normally favor subtle movement.

---

# 6. Still Image Animation

Historical photographs, paintings, illustrations and other still assets can be turned into dynamic shots.

Example:

```text
Historical photograph
        ↓
Crop
        ↓
Slow push-in
        ↓
Subtle movement
        ↓
Text / archival overlay
        ↓
Transition
```

Possible treatments:

* Push in
* Pull out
* Pan
* Drift
* Crop
* Focus movement
* Subtle parallax
* Grain
* Paper texture
* Vignette
* Desaturation
* Sepia when appropriate

Treatments must be used selectively.

The engine must not automatically apply the same effect to every image.

---

# 7. Parallax

Still images may optionally be converted into layered compositions.

Example:

```text
Background
    ↓
Subject
    ↓
Foreground
```

Each layer can move at a different rate to create a 2.5D effect.

Parallax should be used when it improves depth or storytelling.

It should not be applied indiscriminately.

---

# 8. Maps

Maps should be first-class visual assets.

Supported operations:

* Zoom to location
* Pan between locations
* Highlight country
* Highlight city
* Add markers
* Draw routes
* Animate routes
* Add labels
* Focus on a region

Example:

```text
World
  ↓
Europe
  ↓
Germany
  ↓
Animated route
  ↓
South Africa
```

Useful for:

* Wars
* Migration
* Trade
* Oil
* Geopolitics
* Exploration
* Transportation

---

# 9. Diagrams

The engine should support programmatic diagrams for explaining processes.

Example:

```text
COAL
  ↓
GASIFICATION
  ↓
SYNTHESIS
  ↓
HYDROCARBONS
  ↓
LIQUID FUEL
```

Diagram elements should be animatable:

* Arrows
* Labels
* Icons
* Nodes
* Numbers
* Highlight states

Diagrams should be used instead of generated video when a process is better communicated visually through graphics.

---

# 10. Text Animation

The engine should support restrained documentary typography.

Possible animations:

* Fade in
* Fade out
* Slide
* Scale
* Highlight
* Type-on
* Kinetic emphasis

Text can represent:

* Titles
* Dates
* Locations
* Names
* Statistics
* Definitions
* Key statements

Text animation should support the narration rather than distract from it.

---

# 11. Archival Visual Treatment

Historical assets may receive subtle treatment:

* Slight desaturation
* Sepia treatment
* Film grain
* Paper texture
* Vignette
* Exposure variation
* Subtle camera movement

Historical imagery should retain its original character.

Do not automatically make every historical image sepia.

---

# 12. Transitions

Initial transition primitives:

* Hard cut
* Crossfade
* Dip to black
* Dip to white
* Directional movement
* Match transition

Transitions should have narrative purpose.

Avoid excessive transition effects.

---

# 13. Sound Synchronization

Visual composition must remain synchronized with:

* Narration
* BGM
* SFX

Example:

```text
Narration:
"Germany had almost no natural oil."

        ↓

Visual:
Oil field
    ↓
Map
    ↓
Germany highlighted

        ↓

SFX:
Low industrial impact

        ↓

BGM:
Tension increases
```

The timeline remains the source of truth for synchronization.

---

# 14. Renderer Architecture

The application must support renderer abstraction.

```text
                 Renderer Interface
                        │
              ┌─────────┴─────────┐
              ↓                   ↓
       FFmpeg Renderer      Remotion Renderer
```

The rest of the application must not depend directly on a specific rendering implementation.

---

# 15. FFmpeg Renderer

FFmpeg is the primary V1 renderer.

Responsibilities:

* Video assembly
* Image rendering
* Basic transforms
* Audio mixing
* Audio ducking
* SFX
* Captions
* Watermarks
* Encoding
* Format conversion
* Final output

FFmpeg remains the default renderer unless another renderer is explicitly selected.

---

# 16. Remotion Renderer

Remotion is a potential future renderer for advanced visual composition.

Potential responsibilities:

* Complex compositions
* Animated text
* Maps
* Charts
* Diagrams
* Parallax
* Motion graphics
* Advanced camera movement
* Layered compositions

Remotion should not replace FFmpeg by default.

It should be introduced when the visual requirements exceed what is practical with FFmpeg alone.

---

# 17. Renderer Interface

Conceptually:

```python
class Renderer:

    async def render(self, timeline):
        raise NotImplementedError
```

Implementations:

```text
FFmpegRenderer
RemotionRenderer
```

The orchestrator interacts with:

```text
Renderer
```

rather than:

```text
FFmpeg
```

This keeps the system extensible.

---

# 18. Media Rendering vs Creative Composition

The architecture should distinguish two responsibilities.

## Media Rendering

```text
Video
Images
Audio
Cuts
Encoding
Mixing
Captions
Watermarks
```

Primary tool:

```text
FFmpeg
```

## Creative Composition

```text
Maps
Charts
Diagrams
Animated text
Camera movement
Parallax
Motion graphics
Layered compositions
```

Potential tool:

```text
Remotion
```

These capabilities may be combined in the final pipeline.

---

# 19. Example Combined Pipeline

```text
Timeline
   ↓
Shot Composer
   ↓
┌─────────────────────┐
│ Creative Composition│
└──────────┬──────────┘
           ↓
      Remotion
           ↓
    Composed Shots
           ↓
        FFmpeg
           ↓
    Audio + Captions
           ↓
       Watermark
           ↓
      Final Video
```

Not every video needs both renderers.

Simple videos may use FFmpeg only.

Complex documentary sequences may use both.

---

# 20. Cinematic Direction

The Director should eventually generate explicit cinematic instructions.

Example:

```json
{
  "shot": "victorian_woman",
  "direction": {
    "shot_type": "close_up",
    "camera": "push_in",
    "movement_intensity": 0.25,
    "focus": "face",
    "mood": "melancholic"
  }
}
```

The Director determines:

```text
WHAT
WHY
WHEN
```

The Renderer determines:

```text
HOW
```

---

# 21. Example: TB Fashion Video

Narration:

```text
"TB ne sirf logon ki jaan hi nahi li...
usne fashion bhi change kar diya."
```

Possible visual direction:

```text
Shot 1
TB medical engraving
→ slow push-in

Shot 2
Victorian portrait
→ subtle camera movement

Shot 3
Fashion plate
→ slow lateral movement

Shot 4
Victorian cosmetic container
→ detail crop + push-in

Shot 5
Beauty advertisement
→ layered archival composition
```

The sequence should feel like a documentary rather than a slideshow.

---

# 22. Example: Synthetic Oil Video

Narration:

```text
"Germany ke paas oil tha hi nahi...
phir bhi unke tanks chalte rahe."
```

Possible visual direction:

```text
Shot 1
Historical Germany photograph
→ slow push-in

Shot 2
European map
→ zoom toward Germany

Shot 3
Coal photograph
→ transition

Shot 4
Fischer-Tropsch diagram
→ animated process

Shot 5
Leuna industrial imagery
→ slow lateral movement

Shot 6
World map
→ Germany → South Africa route

Shot 7
Sasol / Secunda
→ location reveal
```

---

# 23. Creative Rules

The engine should follow these principles:

1. Movement must have a storytelling purpose.
2. Do not animate every element.
3. Prefer subtle movement for documentary content.
4. Use static frames when information needs emphasis.
5. Use maps for geography.
6. Use diagrams for processes.
7. Prefer real archival assets when available.
8. Use AI-generated media when real assets are unavailable or unsuitable.
9. Avoid excessive transitions.
10. Preserve historical authenticity.
11. Match visual intensity to narrative intensity.
12. Sound and visuals should reinforce each other.

---

# 24. V1 Scope

V1 should remain simple.

Support:

* Static images
* Video clips
* Push in/out
* Pan
* Crop
* Basic transitions
* Text overlays
* Captions
* Audio synchronization
* BGM
* Audio ducking
* SFX
* Watermark
* FFmpeg rendering

No advanced cinematic renderer is required for V1.

---

# 25. V2 Scope

Add:

* Advanced camera primitives
* Better text animation
* Map animations
* Animated diagrams
* Layered compositions
* Parallax
* Reusable visual templates
* Advanced transitions
* Scene-level composition

---

# 26. V3 Scope

Potentially add:

* Remotion renderer
* Advanced motion graphics
* Automated visual choreography
* AI-generated cinematography instructions
* Automatic shot pacing
* Scene-level visual continuity
* Style-specific cinematography
* Dynamic maps
* Dynamic charts
* Complex documentary compositions

---

# 27. Watermarking

Watermarking remains a final-render operation.

Generated assets must remain clean.

```text
Generated Media
      ↓
Master Render
      ↓
┌─────────────┬──────────────┐
↓             ↓              ↓
YouTube     Instagram      Archive
ON            ON             OFF
```

Watermarking should be implemented through FFmpeg initially.

It should remain configurable:

```yaml
branding:
  enabled: true
  asset: branding/logo.png
  position: bottom_right
  margin: 40
  opacity: 0.65
  width_percent: 4
```

---

# 28. Long-Form Support

The cinematic composition system must support both short-form and long-form output.

Example:

```text
Short:
30–60 seconds
9:16

Long-form:
~10 minutes
16:9
```

The same Timeline/Scene/Shot architecture should be used.

The difference should primarily be:

* Duration
* Aspect ratio
* Story structure
* Pacing
* Output configuration

---

# 29. Short-Form vs Long-Form

## Short-Form

Prioritize:

* Immediate hook
* Fast pacing
* Strong visual changes
* One central idea
* High information density

## Long-Form

Prioritize:

* Story development
* Context
* Chapter structure
* Slower pacing
* Visual variety
* Deeper explanation

The renderer itself should not contain separate video-generation logic for each format.

---

# 30. Content Reuse

One research project should eventually support multiple outputs.

Example:

```text
Research
   ↓
Master Story
   ↓
10-minute Documentary
   ↓
Short-form extraction
   ├── Short #1
   ├── Short #2
   ├── Short #3
   ├── Short #4
   └── Short #5
```

This should be supported by the Timeline/Director architecture rather than manually recreating videos.

---

# 31. Success Criteria

The cinematic composition system is successful when:

```text
One archival photograph
```

can become:

```text
A directed documentary shot
```

without requiring manual editing in Premiere, After Effects, or another traditional editor.

The system should eventually support:

```text
Script
  ↓
Director
  ↓
Shot Direction
  ↓
Renderer
  ↓
Cinematic Sequence
```

with minimal human intervention.

---

# 32. Core Principle

The objective is not:

> Add more effects.

The objective is:

> Give the AI the vocabulary of cinematography and let the renderer execute it.

The Director decides:

```text
WHAT
WHY
WHEN
```

The Renderer decides:

```text
HOW
```

The final result should feel intentionally directed rather than algorithmically decorated.

```

**This one can replace the shorter `CINEMATIC_COMPOSITION_SCOPE.md` file.** It now covers the entire scope in one place: FFmpeg, future Remotion support, cinematography, maps, diagrams, parallax, long-form, watermarking, and the V1→V3 progression.
```
