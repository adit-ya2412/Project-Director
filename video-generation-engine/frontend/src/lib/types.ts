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
  | "created"
  | "script_uploaded"
  | "awaiting_approval"
  | "awaiting_review"
  | "rendering"
  | "completed"
  | "failed";

export interface Project {
  id: string;
  name: string;
  status: ProjectStatus;
  script: string | null;
  render_style?: string | null;
  frame_aspect?: string | null;
  language_code?: string | null;
  render_width?: number | null;
  render_height?: number | null;
  timeline: Timeline | null;
  video_path: string | null;
  error: string | null;
  created_at: string;
  updated_at: string;
}

// -- Timeline IR (only the fields the frontend actually reads) --------------

export type ProducedBy =
  | "director"
  | "scene_planner"
  | "shot_planner"
  | "asset_planner"
  | "narration"
  | "human"
  | "music_selection";

export type TimelineStatus =
  "draft" | "awaiting_approval" | "approved" | "superseded";

export interface MusicTrackSelection {
  provider: string;
  track_id: string;
  source_url: string;
  licence: string;
  attribution: string;
  content_hash: string;
}

export interface ActMusicBed {
  act_id: string
  selected_track: MusicTrackSelection | null
}

export interface MusicPlan {
  mood: string
  tempo: string
  energy_arc: string
  search_terms: string[]
  licence_requirements: string[]
  selected_track: MusicTrackSelection | null
  selection_attempted: boolean
  act_beds?: ActMusicBed[]
}

export interface CreativeContext {
  tone: string;
  visual_style: string;
  historical_period: string;
  audience: string;
  camera_language: string;
  colour_palette: string[];
  constraints: string[];
}

export interface TimelineMetadata {
  language: string;
  aspect_ratio: string;
  resolution: [number, number];
  frame_aspect?: string | null;
  fps: number;
  total_duration_s: number;
  voice_id: string | null;
  language_code?: string | null;
  narration_locked: boolean;
  approved_scenes?: string[];
}

export interface Timeline {
  schema_version: string;
  timeline_id: string;
  project_id: string;
  version: number;
  parent_version: number | null;
  produced_by: ProducedBy;
  status: TimelineStatus;
  created_at: string;
  metadata: TimelineMetadata;
  creative_context: CreativeContext;
  music_plan: MusicPlan | null;
  scenes: Scene[];
}

export interface Scene {
  id: string;
  order: number;
  title: string;
  summary: string;
  emotion: string;
  narrative_purpose: string;
  narration_text: string;
  duration_s: number;
  shots: Shot[];
  act_id?: string | null;
}

export type CameraMovement =
  "static" | "slow_zoom" | "slow_push" | "pull_back" | "pan" | "split_frame";

export interface Camera {
  movement: CameraMovement;
  direction: "in" | "out" | "left" | "right" | "none";
  intensity: number;
}

export interface Shot {
  id: string;
  order: number;
  intent: string;
  intent_text: string;
  narration_span: [number, number] | null;
  duration_s: number;
  framing: string;
  camera: Camera;
  prompt: string;
  asset_locked: boolean;
}

// -- GET /projects/{id}/progress --------------------------------------------

export type ShotBindingState =
  | "pending"
  | "awaiting_generation"
  | "resolved"
  | "generated"
  | "failed"
  | string; // the binding state machine may grow states; don't hard-fail on an unknown one

/** Where a bound asset actually came from — the thing the spec says the
 * user reacts to most (F4/F6). Derived client-side from `asset.provider` /
 * `asset.licence`, since the backend doesn't hand back one pre-baked enum. */
export type AssetSource =
  "archival" | "entity" | "generated" | "uploaded" | "unknown";

export interface ShotAssetDetail {
  provider: string;
  source_url: string | null;
  licence: string;
  attribution: string | null;
  local_path: string;
}

export interface ShotClipDetail {
  provider: string;
  model_id: string;
  status: string;
  local_path: string;
  // Not present on the backend today (only the final ShotBinding.last_error
  // survives past exhausted regeneration attempts) — read defensively in
  // case a future backend change surfaces the vision-check verdict per clip.
  violated_constraint?: string | null;
  error?: string | null;
}

export interface ShotProgress {
  shot_id: string;
  scene_id?: string;
  state: ShotBindingState;
  rung: string | null;
  last_error: string | null;
  will_generate: boolean;
  locked: boolean;
  asset: ShotAssetDetail | null;
  clip: ShotClipDetail | null;
  says: string | null;
  prompt: string;
  intent: string;
  duration_s: number;
  starts_at_s: number | null;
}

/** F3: frontend rendering decision only. The backend always uses
 * `metadata.approved_scenes`; putting this number in `is_satisfied`
 * would recreate R1. ~40 shots is about 3 minutes of output. */
export const SCENE_GROUP_SHOT_THRESHOLD = 40;

/** C5: scene summary on GET /progress. The threshold that switches the
 * review UI from a flat grid to this grouping lives in the frontend
 * only (`SCENE_GROUP_SHOT_THRESHOLD`) — the backend always has this. */
export interface SceneProgress {
  id: string;
  act_id: string | null;
  title: string;
  shot_ids: string[];
  total_shots: number;
  completed_shots: number;
  failed_shots: number;
  unfilled_shots: number;
  approved: boolean;
  starts_at_s: number | null;
  regenerate_failed_cost_cents: number;
}

export interface ProgressResponse {
  project_id: string;
  status: ProjectStatus;
  workflow_state: string | null;
  current_step: string | null;
  total_shots: number;
  completed_shots: number;
  failed_shots: number;
  progress: number | null;
  // Fixed by Task 5 (2026-08-16, the one-gate redesign): now counts every
  // shot the search pass has already deferred to generation
  // (`awaiting_generation`), not only shots whose plan-primary strategy
  // happens to be a generation rung — safe to display.
  estimated_cost_cents: number;
  spent_cost_cents: number;
  budget_cap_cents: number;
  shots: ShotProgress[];
  scenes?: SceneProgress[];
}

// -- POST /projects/{id}/assets ----------------------------------------------

export interface UploadedAssetResult {
  asset_id: string;
  filename: string;
  duplicate: boolean;
}

// -- Every 202 trigger (render, approve, override, retry*) ------------------

export interface WorkflowTriggerResult {
  project_id: string;
  workflow_run_id: string;
  state: string;
  joined_existing_run: boolean;
}

// -- POST /projects/{id}/music/upload ----------------------------------------

export interface MusicUploadResult extends WorkflowTriggerResult {
  /** Decision 6a/6b: length never rejects; these are the human-readable
   * "will loop N times" / "using the first X of Y" notices. */
  warnings: string[];
}

// -- POST /projects/{id}/shots/{shot_id}/generate ----------------------------

export interface GenerateShotImageResult {
  shot_id: string;
  clip_id: string;
  cost_cents: number;
  cache_hit: boolean;
}

export interface SceneApprovalResult {
  scene_id: string;
  approved: boolean;
  approved_scenes: string[];
  all_scenes_approved: boolean;
}

export interface RegenerateFailedResult {
  scene_id: string;
  shot_ids: string[];
  estimated_cost_cents: number;
  regenerated: boolean;
  results: GenerateShotImageResult[];
}

// -- POST /projects/{id}/script/preflight -----------------------------------

export interface FragmentEstimate {
  index: number;
  text: string;
  estimated_duration_s: number;
}

export interface BreakSuggestion {
  offset: number;
  mark: string;
  preview_before: string;
  preview_after: string;
  reason: string;
}

export interface StyleSuitability {
  suitable: boolean;
  reason: string;
}

export interface ScriptPreflightResponse {
  style: string;
  passed: boolean;
  violations: string[];
  warnings: string[];
  fragment_count: number;
  estimated_total_duration_s: number;
  estimated_average_shot_duration_s: number;
  fragments: FragmentEstimate[];
  suggested_breaks: BreakSuggestion[];
  further_suggestions_available: boolean;
  suggestions_would_pass: boolean;
  punctuation_cannot_fix: string[];
  suitability: StyleSuitability | null;
}

export interface RewriteFeasibility {
  passed: boolean;
  violations: string[];
  fragment_count: number;
  estimated_total_duration_s: number;
  estimated_average_shot_duration_s: number;
}

export interface ScriptRewriteResponse {
  attempted: boolean;
  accepted: boolean;
  rejection_reasons: string[];
  rewritten_script: string;
  original_fragment_count: number;
  rewritten_fragment_count: number;
  feasibility: RewriteFeasibility | null;
  persisted: boolean;
}
