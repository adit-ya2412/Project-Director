# FFmpeg Watermark

## Purpose

Add channel branding to the final rendered video using FFmpeg.

This is a small rendering-layer feature and does not require changes to the timeline, scene, shot, or asset pipeline.

## Architecture

```text
Timeline
   ↓
Scene/Shot Rendering
   ↓
Audio + Captions
   ↓
FFmpeg Final Render
   ↓
Watermark Overlay
   ↓
Final Video

branding:
  enabled: true
  asset: branding/logo.png
  position: bottom_right
  margin: 40
  opacity: 0.65
  width_percent: 4

  Master Render
    ↓
├── YouTube version     → watermark ON
├── Instagram version   → watermark ON
└── Archive version     → watermark OFF