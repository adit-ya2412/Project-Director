/**
 * Human-facing labels for the five `render_style` presets.
 *
 * IDs and `targetShotDurationS` are mirrored from
 * `backend/app/script/styles.py::STYLE_PACING_BANDS` (verified 2026-09-04):
 *   documentary_archival  target=None   1280×720
 *   retention_fast        target=1.75   720×1280
 *   archival_montage      target=2.25   720×1280  (reasoned starting point)
 *   stillness             target=None   1280×720 (9:16 opt-in)
 *   illustrated_risograph target=None   720×1280 (16:9 opt-in — the
 *     opposite direction from stillness; both opt-ins are read through
 *     `styleAcceptsFrameAspect`/`canvasForStyle` in ./resolution, which
 *     mirror the backend's `style_accepts_frame_aspect` single source of
 *     truth rather than comparing a style id to a literal per call site)
 *
 * Grade copy is from `backend/app/renderer/grading.py::STYLE_GRADES`.
 *
 * NO `previewSrc` — preview stills were built and then REMOVED
 * 2026-08-26 (ui_style_feature_coverage.md §5, P-UI6). The first attempt
 * was four 720x1280 crops of one car photo at four grades, which was
 * wrong three ways: `documentary_archival` and `stillness` actually
 * render 1280x720 LANDSCAPE, so half the previews showed the wrong
 * aspect — the single most decision-relevant difference between these
 * styles; the grade deltas were imperceptible at thumbnail size; and a
 * modern car photo misrepresents the output genre of a tool that makes
 * archival documentaries. A wrong preview is worse than none (it creates
 * a false expectation where absent previews just let the hint text do
 * its job). `OptionCard`'s `preview` slot is still there for whenever
 * real, per-style, correct-aspect assets exist.
 */

import type { CameraMovement, SfxKind, TransitionType } from './types'

export const RENDER_STYLES = [
  {
    id: 'documentary_archival',
    label: 'Archival documentary',
    hint: '16:9 · Ken Burns, YouTube long-form',
    targetShotDurationS: null,
    gradeHint: 'Muted, slightly desaturated',
  },
  {
    id: 'retention_fast',
    label: 'Fast-cut reel',
    hint: '9:16 · punchy cuts, short feed',
    targetShotDurationS: 1.75,
    gradeHint: 'Punchy contrast, saturated',
  },
  {
    id: 'stillness',
    label: 'Stillness',
    hint: 'Quiet, contemplative — pick a frame below',
    targetShotDurationS: null,
    gradeHint: 'Quieter, slightly darker',
  },
  {
    id: 'archival_montage',
    label: 'Archival montage',
    hint: '9:16 · harder cuts, frequent text cards',
    targetShotDurationS: 2.25,
    gradeHint: 'Punchier than archival, short of social-pop',
  },
  {
    id: 'illustrated_risograph',
    label: 'Illustrated risograph',
    hint: '9:16 · fully AI-illustrated, faceless characters — pick a frame below',
    targetShotDurationS: null,
    gradeHint: 'Neutral — the look is baked into the generation prompt, not a grade',
  },
] as const

export type RenderStyleId = (typeof RENDER_STYLES)[number]['id']

export const STYLE_LABEL: Record<string, string> = Object.fromEntries(
  RENDER_STYLES.map((s) => [s.id, s.label]),
)

export function styleLabel(id: string | null | undefined): string {
  if (!id) return 'No style set'
  return STYLE_LABEL[id] ?? id
}

export const TRANSITION_LABEL: Record<TransitionType, string> = {
  cut: 'cut',
  dissolve: 'dissolve',
  fade: 'fade',
  wipeleft: 'wipe left',
  fadeblack: 'fade to black',
  glitch_shift: 'glitch shift',
  glitch_tear: 'glitch tear',
  glitch_jitter: 'glitch jitter',
}

export const CAMERA_LABEL: Record<CameraMovement, string> = {
  static: 'static',
  slow_zoom: 'slow zoom',
  slow_push: 'slow push',
  pull_back: 'pull back',
  pan: 'pan',
  split_frame: 'split frame',
  punch_in: 'punch in',
}

export const SFX_KIND_LABEL: Record<SfxKind, string> = {
  whoosh: 'Whoosh (punch-in)',
  stinger: 'Stinger (text card)',
  transition: 'Transition (xfade)',
}
