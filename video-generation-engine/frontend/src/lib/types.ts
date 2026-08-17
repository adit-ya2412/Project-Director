/**
 * Types mirroring backend/app/schemas/{project,timeline}.py and the
 * dict shapes returned by backend/app/api/projects.py.
 *
 * The backend's OpenAPI schema could not be fetched (server was not
 * running when this frontend was built) so these were hand-derived by
 * reading the Pydantic models and route handlers directly. Anything
 * marked "landing shortly" in the F0b work is typed against the agreed
 * contract, not something observed live.
 */

export type ProjectStatus =
  | 'created'
  | 'script_uploaded'
  | 'awaiting_approval'
  | 'awaiting_review'
  | 'rendering'
  | 'completed'
  | 'failed'

export interface Project {
  id: string
  name: string
  status: ProjectStatus
  script: string | null
  timeline: Timeline | null
  video_path: string | null
  error: string | null
  created_at: string
  updated_at: string
}

// -- Timeline IR (only the fields the frontend actually reads) --------------

export type ProducedBy =
  | 'director'
  | 'scene_planner'
  | 'shot_planner'
  | 'asset_planner'
  | 'narration'
  | 'human'
  | 'music_selection'

export type TimelineStatus = 'draft' | 'awaiting_approval' | 'approved' | 'superseded'

export interface MusicTrackSelection {
  provider: string
  track_id: string
  source_url: string
  licence: string
  attribution: string
  content_hash: string
}

export interface MusicPlan {
  mood: string
  tempo: string
  energy_arc: string
  search_terms: string[]
  licence_requirements: string[]
  selected_track: MusicTrackSelection | null
  selection_attempted: boolean
}

export interface CreativeContext {
  tone: string
  visual_style: string
  historical_period: string
  audience: string
  camera_language: string
  colour_palette: string[]
  constraints: string[]
}

export interface TimelineMetadata {
  language: string
  aspect_ratio: string
  resolution: [number, number]
  fps: number
  total_duration_s: number
  voice_id: string | null
  narration_locked: boolean
}

export interface Timeline {
  schema_version: string
  timeline_id: string
  project_id: string
  version: number
  parent_version: number | null
  produced_by: ProducedBy
  status: TimelineStatus
  created_at: string
  metadata: TimelineMetadata
  creative_context: CreativeContext
  music_plan: MusicPlan | null
  scenes: Scene[]
}

export interface Scene {
  id: string
  order: number
  title: string
  summary: string
  emotion: string
  narrative_purpose: string
  narration_text: string
  duration_s: number
  shots: Shot[]
}

export type CameraMovement =
  | 'static'
  | 'slow_zoom'
  | 'slow_push'
  | 'pull_back'
  | 'pan'
  | 'split_frame'

export interface Camera {
  movement: CameraMovement
  direction: 'in' | 'out' | 'left' | 'right' | 'none'
  intensity: number
}

export interface Shot {
  id: string
  order: number
  intent: string
  intent_text: string
  narration_span: [number, number] | null
  duration_s: number
  framing: string
  camera: Camera
  prompt: string
  asset_locked: boolean
}

// -- GET /projects/{id}/progress --------------------------------------------

export type ShotBindingState =
  | 'pending'
  | 'awaiting_generation'
  | 'resolved'
  | 'generated'
  | 'failed'
  | string // the binding state machine may grow states; don't hard-fail on an unknown one

/** Where a bound asset actually came from — the thing the spec says the
 * user reacts to most (F4/F6). Derived client-side from `asset.provider` /
 * `asset.licence`, since the backend doesn't hand back one pre-baked enum. */
export type AssetSource = 'archival' | 'entity' | 'generated' | 'uploaded' | 'unknown'

export interface ShotAssetDetail {
  provider: string
  source_url: string | null
  licence: string
  attribution: string | null
  local_path: string
}

export interface ShotClipDetail {
  provider: string
  model_id: string
  status: string
  local_path: string
  // Not present on the backend today (only the final ShotBinding.last_error
  // survives past exhausted regeneration attempts) — read defensively in
  // case a future backend change surfaces the vision-check verdict per clip.
  violated_constraint?: string | null
  error?: string | null
}

export interface ShotProgress {
  shot_id: string
  state: ShotBindingState
  rung: string | null
  last_error: string | null
  will_generate: boolean
  locked: boolean
  asset: ShotAssetDetail | null
  clip: ShotClipDetail | null
  says: string | null
  prompt: string
  intent: string
  duration_s: number
  starts_at_s: number | null
}

export interface ProgressResponse {
  project_id: string
  status: ProjectStatus
  workflow_state: string | null
  current_step: string | null
  total_shots: number
  completed_shots: number
  failed_shots: number
  progress: number | null
  // Fixed by Task 5 (2026-08-16, the one-gate redesign): now counts every
  // shot the search pass has already deferred to generation
  // (`awaiting_generation`), not only shots whose plan-primary strategy
  // happens to be a generation rung — safe to display.
  estimated_cost_cents: number
  spent_cost_cents: number
  shots: ShotProgress[]
}

// -- POST /projects/{id}/assets ----------------------------------------------

export interface UploadedAssetResult {
  asset_id: string
  filename: string
  duplicate: boolean
}

// -- Every 202 trigger (render, approve, override, retry*) ------------------

export interface WorkflowTriggerResult {
  project_id: string
  workflow_run_id: string
  state: string
  joined_existing_run: boolean
}

// -- POST /projects/{id}/shots/{shot_id}/generate ----------------------------

export interface GenerateShotImageResult {
  shot_id: string
  clip_id: string
  cost_cents: number
  cache_hit: boolean
}
