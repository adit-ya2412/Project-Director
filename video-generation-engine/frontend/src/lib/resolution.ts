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
 *     `_MAX_PAN_ZOOM_DELTA = 0.3` for pan, both `1 + intensity * delta`;
 *     static/split_frame never move, so their zoom is exactly 1.0).
 */

import type { Camera } from './types'

export const RENDER_WIDTH = 720
export const RENDER_HEIGHT = 1280
const RENDER_ASPECT = RENDER_WIDTH / RENDER_HEIGHT // 9:16 portrait

const MAX_ZOOM_DELTA = 0.5
const MAX_PAN_ZOOM_DELTA = 0.3

export function effectiveKenBurnsZoom(camera: Camera | undefined): number {
  if (!camera) return 1
  switch (camera.movement) {
    case 'slow_zoom':
    case 'slow_push':
    case 'pull_back':
      return Math.max(1, 1 + camera.intensity * MAX_ZOOM_DELTA)
    case 'pan':
      return Math.max(1, 1 + camera.intensity * MAX_PAN_ZOOM_DELTA)
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
function usableSourceArea(width: number, height: number): number {
  const sourceAspect = width / height
  if (sourceAspect > RENDER_ASPECT) {
    // Wider than the target: crop width, keep full height.
    const usableWidth = height * RENDER_ASPECT
    return usableWidth * height
  }
  // Taller/narrower than the target (or an exact match): crop height, keep full width.
  const usableHeight = width / RENDER_ASPECT
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
): ResolutionWarning {
  const zoom = effectiveKenBurnsZoom(camera)
  const targetArea = RENDER_WIDTH * RENDER_HEIGHT * zoom * zoom
  const sourceArea = usableSourceArea(width, height)
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
  const targetDims = `${RENDER_WIDTH}×${RENDER_HEIGHT}`

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
