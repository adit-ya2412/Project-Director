/**
 * Human labels for `current_step` (`GET /progress`), matching
 * backend/app/workflow/engine.py's `DEFAULT_PIPELINE` order exactly —
 * see each step's own `name` class attribute under app/workflow/steps/.
 */
export const STEP_ORDER = [
  'generate_timeline',
  'resolve_assets_search',
  'select_music',
  'await_approval',
  'narration',
  'resolve_assets_generate',
  'await_review',
  'render',
  'complete',
] as const

export type StepName = (typeof STEP_ORDER)[number]

export const STEP_LABEL: Record<StepName, string> = {
  generate_timeline: 'Planning the story — scenes, shots and camera',
  resolve_assets_search: 'Searching for existing footage and images',
  select_music: 'Choosing background music',
  await_approval: 'Waiting for your approval',
  narration: 'Recording narration',
  resolve_assets_generate: 'Generating images for the remaining shots',
  await_review: 'Waiting for a fix to a failed shot',
  render: 'Rendering the video',
  complete: 'Done',
}

export function stepLabel(step: string | null | undefined): string {
  if (!step) return 'Starting up'
  return STEP_LABEL[step as StepName] ?? step
}

export function stepIndex(step: string | null | undefined): number {
  if (!step) return -1
  return STEP_ORDER.indexOf(step as StepName)
}

const AWAIT_APPROVAL_INDEX = STEP_ORDER.indexOf('await_approval')

/** True before (or still at) `await_approval` — `null`/unknown counts as
 * pre-approval too, since that's the state before the engine has reported
 * any step at all. Compares indices rather than `.includes()` on a plain
 * `string`, which is what a `StepName[]` typed array can't accept directly. */
export function isPreApproval(step: string | null | undefined): boolean {
  const idx = stepIndex(step)
  return idx === -1 || idx <= AWAIT_APPROVAL_INDEX
}
