/**
 * F7 — resolution warnings on human-supplied images. Warn, never block.
 *
 * Mirrors the real math the backend uses elsewhere (never checked for
 * override uploads today — that is the whole gap F7 closes):
 *   - upscale factor: `sqrt(target_area / source_area)`, the same formula
 *     `_quality_score` uses in app/assets/ranking.py.
 *   - render target: `settings.render_width/height` = 720x1280
 *     (backend/app/core/config.py) — hardcoded here since there's no
 *     settings endpoint; update both sides if that config ever changes.
 *   - Ken Burns zoom: mirrors backend/app/renderer/ken_burns.py exactly
 *     (`_MAX_ZOOM_DELTA = 0.5` for slow_zoom/slow_push/pull_back,
 *     `_MAX_PAN_ZOOM_DELTA = 0.3` for pan,
 *     `_MAX_PUNCH_ZOOM_DELTA = 0.9` for punch_in,
 *     both `1 + intensity * delta`; static/split_frame never move, so
 *     their zoom is exactly 1.0).
 */

import type { Camera } from './types'

export const RENDER_WIDTH = 720
export const RENDER_HEIGHT = 1280

/** Mirrors `resolve_render_format` (backend/app/script/styles.py).
 * Hardcoded because there is no settings endpoint; archival/stillness
 * default 16:9, stillness + `9:16` is a vertical Ken Burns reel,
 * retention_fast and archival_montage stay 9:16.
 *
 * `archival_montage` was MISSING from this switch until 2026-08-26
 * (ui_style_feature_coverage.md §3.1.1) — it silently fell through to
 * the 16:9 default, which is wrong (backend `STYLE_PACING_BANDS
 * ["archival_montage"]` is 720x1280, verified live against
 * backend/app/script/styles.py before adding this line, not copied from
 * a plan doc). A real, if narrow, client-only bug: the actual render was
 * always correct (server-side), only this file's own Ken Burns/
 * resolution-warning math was wrong for that one style. */
export function canvasForStyle(
  style: string,
  frameAspect?: string | null,
): { width: number; height: number } {
  if (style === "retention_fast" || style === "archival_montage") {
    return { width: 720, height: 1280 }
  }
  if (style === "stillness" && frameAspect === "9:16") return { width: 720, height: 1280 }
  return { width: 1280, height: 720 }
}

export function renderAspect(width = RENDER_WIDTH, height = RENDER_HEIGHT): number {
  return width / height
}

export function frameAspectClass(width?: number | null, height?: number | null): string {
  if (width && height && width > height) return "aspect-video"
  return "aspect-[9/16]"
}

const MAX_ZOOM_DELTA = 0.5
const MAX_PAN_ZOOM_DELTA = 0.3
// backend/app/renderer/ken_burns.py `_MAX_PUNCH_ZOOM_DELTA` — punch_in
// is a hard stepped zoom, a larger ceiling than the slow-drift constant
// on purpose. Missing here until 2026-08-26 (same pass as types.ts's
// punch_in enum fix, ui_style_feature_coverage.md §2.3).
const MAX_PUNCH_ZOOM_DELTA = 0.9

export function effectiveKenBurnsZoom(camera: Camera | undefined): number {
  if (!camera) return 1
  switch (camera.movement) {
    case 'slow_zoom':
    case 'slow_push':
    case 'pull_back':
      return Math.max(1, 1 + camera.intensity * MAX_ZOOM_DELTA)
    case 'pan':
      return Math.max(1, 1 + camera.intensity * MAX_PAN_ZOOM_DELTA)
    case 'punch_in':
      return Math.max(1, 1 + camera.intensity * MAX_PUNCH_ZOOM_DELTA)
    case 'static':
    case 'split_frame':
    default:
      return 1
  }
}

/**
 * The pixels actually usable after the 9:16 crop-to-fill — a landscape
 * source loses width, a very-tall source loses height. Using this instead
 * of the full source frame is F7's "score the post-crop region" note.
 */
function usableSourceArea(
  width: number,
  height: number,
  targetWidth = RENDER_WIDTH,
  targetHeight = RENDER_HEIGHT,
): number {
  const sourceAspect = width / height
  const targetAspect = renderAspect(targetWidth, targetHeight)
  if (sourceAspect > targetAspect) {
    const usableWidth = height * targetAspect
    return usableWidth * height
  }
  const usableHeight = width / targetAspect
  return width * usableHeight
}

export type ResolutionVerdict = 'fine' | 'soft' | 'bad'

export interface ResolutionWarning {
  verdict: ResolutionVerdict
  upscale: number
  message: string
}

/**
 * @param width source image width in pixels
 * @param height source image height in pixels
 * @param camera the bound shot's camera, when known (Gate 1, where the
 *   specific shot is known); omit for a generic upload-time check (F2's
 *   asset uploads aren't bound to a shot yet, so 1x is the honest default).
 */
export function computeResolutionWarning(
  width: number,
  height: number,
  camera?: Camera,
  targetWidth = RENDER_WIDTH,
  targetHeight = RENDER_HEIGHT,
): ResolutionWarning {
  const zoom = effectiveKenBurnsZoom(camera)
  const targetArea = targetWidth * targetHeight * zoom * zoom
  const sourceArea = usableSourceArea(width, height, targetWidth, targetHeight)
  const upscale = Math.sqrt(targetArea / sourceArea)

  // Table from F7: <=1.5x fine, 1.5-2.5x soft, >=4x bad. The spec leaves
  // 2.5-4x unlabelled; treated as still "soft" (rather than inventing an
  // unlabelled third tier) since "bad" is only ever defined starting at 4x.
  let verdict: ResolutionVerdict
  if (upscale <= 1.5) verdict = 'fine'
  else if (upscale < 4) verdict = 'soft'
  else verdict = 'bad'

  const upscaleText = `${upscale.toFixed(1)}×`
  const dims = `${Math.round(width)}×${Math.round(height)}`
  const targetDims = `${targetWidth}×${targetHeight}`

  let message: string
  if (verdict === 'fine') {
    message = `${dims} → upscaled ${upscaleText} to fill ${targetDims}. Looks fine at this size.`
  } else if (verdict === 'soft') {
    message = `${dims} → upscaled ${upscaleText} to fill ${targetDims}, may look soft.`
  } else {
    message = `${dims} → upscaled ${upscaleText} to fill ${targetDims}, will likely look bad.`
  }

  return { verdict, upscale, message }
}

/** Reads a File's pixel dimensions in the browser, no upload required. */
export function readImageDimensions(file: File): Promise<{ width: number; height: number }> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file)
    const img = new Image()
    img.onload = () => {
      resolve({ width: img.naturalWidth, height: img.naturalHeight })
      URL.revokeObjectURL(url)
    }
    img.onerror = () => {
      URL.revokeObjectURL(url)
      reject(new Error('could not read image dimensions'))
    }
    img.src = url
  })
}

/** Same, for a video file - `<video>` exposes its intrinsic size on
 * `loadedmetadata`, which fires without downloading the whole clip.
 * Split out rather than folded into the function above so an image never
 * pays for a video element and vice versa. */
export function readVideoDimensions(file: File): Promise<{ width: number; height: number }> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file)
    const video = document.createElement('video')
    video.preload = 'metadata'
    video.onloadedmetadata = () => {
      resolve({ width: video.videoWidth, height: video.videoHeight })
      URL.revokeObjectURL(url)
    }
    video.onerror = () => {
      URL.revokeObjectURL(url)
      reject(new Error('could not read video dimensions'))
    }
    video.src = url
  })
}

/** Dimensions for whichever kind of media the user picked. The override
 * endpoint accepts an image OR a video (2026-09-02), and the resolution
 * warning is worth showing for both - a 480p clip on a 1280-wide canvas
 * upscales exactly as badly as a 480px photo would. */
export function readMediaDimensions(file: File): Promise<{ width: number; height: number }> {
  return file.type.startsWith('video/') || /\.(mp4|mov|webm|mkv)$/i.test(file.name)
    ? readVideoDimensions(file)
    : readImageDimensions(file)
}
