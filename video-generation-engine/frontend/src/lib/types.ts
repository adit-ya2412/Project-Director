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

// -- SFX (analysis.md C3f; ui_style_feature_coverage.md §3.4) --------------

export type SfxKind = "whoosh" | "stinger" | "transition";

export interface SfxClipSelection {
  kind: SfxKind;
  provider: string;
  track_id: string;
  source_url: string;
  licence: string;
  attribution: string;
  content_hash: string;
  // C3c/C3d; optional on every pre-C3c timeline.
  peak_dbfs?: number | null;
  duration_s?: number | null;
}

export interface SfxPlan {
  queries: Record<string, string[]>;
  licence_requirements: string[];
  // Which kinds are actually present varies by style — e.g.
  // `retention_fast` has `whoosh_enabled=False` (analysis.md decision
  // 5/5a), so a real `retention_fast` timeline's `clips` never includes
  // a `whoosh` entry even though `queries` may still name one. Render
  // SFX UI from this array, never from an assumed fixed 3-kind set.
  clips: SfxClipSelection[];
  selection_attempted: boolean;
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
  // Frozen at create_initial from project.render_style
  // (backend/app/schemas/timeline.py TimelineMetadata.render_style).
  render_style?: string | null;
  // Independent of render_style. `null` means "use render_style's own
  // grade". Settable any time via POST /grade (ui_style_feature_coverage.md
  // §3.3). Cross-checked 2026-08-26 against
  // backend/app/schemas/timeline.py:348.
  grade_style?: string | null;
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
  sfx_plan: SfxPlan | null;
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

// `punch_in` was missing here until 2026-08-26 (ui_style_feature_coverage.md
// §2.3) — a real drift found by cross-checking against the backend enum
// (backend/app/schemas/timeline.py), not assumed. `retention_fast`'s own
// prompt fragment uses it as its default camera move.
export type CameraMovement =
  | "static"
  | "slow_zoom"
  | "slow_push"
  | "pull_back"
  | "pan"
  | "split_frame"
  | "punch_in";

export interface Camera {
  movement: CameraMovement;
  direction: "in" | "out" | "left" | "right" | "none";
  intensity: number;
}

// style_extensions.md §5 (Feature C): the three glitch_* values are NOT
// real `xfade` transition names — they're a custom RGB-split + noise
// filter fragment, chosen by the Shot Planner at most once per video for
// a "something is failing/being exposed" beat. Nothing to configure
// client-side; see ui_style_feature_coverage.md §1.4 for why this stays
// read-only (§3.2/§3.6), not a picker.
export type TransitionType =
  | "cut"
  | "dissolve"
  | "fade"
  | "wipeleft"
  | "fadeblack"
  | "glitch_shift"
  | "glitch_tear"
  | "glitch_jitter";

export const GLITCH_TRANSITIONS: readonly TransitionType[] = [
  "glitch_shift",
  "glitch_tear",
  "glitch_jitter",
];

export interface Transition {
  type: TransitionType;
  duration_s: number;
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
  transition_out: Transition;
  prompt: string;
  // style_extensions.md §4.4 (Feature B): a short structural title/
  // heading burned full-frame over this shot. Empty/`null` on almost
  // every shot — only `archival_montage`'s own prompt fragment asks for
  // these with any frequency (roughly one every 4-6 shots).
  text_card: string | null;
  // long_form_direction.md A8/A12: a planner-authored phrase naming a
  // diegetic sound this shot's beat genuinely turns on (e.g. "a distant
  // church bell tolling"), generated into a real clip by the paid,
  // post-approval `generate_diegetic_sfx` step. Empty/`null` on almost
  // every shot — the planner's own restraint (`app/prompts/shot_planner/
  // v1.md`) is the only thing limiting how many a video gets. When set,
  // it is a spend the reviewer is approving (~6c, `sfx_diegetic_cost_
  // cents_estimate`) sight-unseen unless the gate shows it.
  sfx_cue: string | null;
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

/** P3a (docs/plans/gate_panel_overrides.md): the split-screen BOTTOM
 * panel — `null` for every shot that isn't `camera_movement ===
 * "split_frame"`, an object otherwise, regardless of whether that panel
 * has resolved yet (`asset`/`clip` are `null` while unresolved,
 * `state`/`last_error` say why). That presence/absence split is the
 * signal to use, not `asset`/`clip` being non-null — a split_frame shot
 * with an unresolved bottom panel is NOT the same as a shot with no
 * bottom panel at all. Mirrors `ShotAssetDetail`/`ShotClipDetail`'s own
 * shape rather than inventing a different one for the second panel. */
export interface ShotSecondaryPanel {
  prompt: string;
  state: ShotBindingState | null;
  last_error: string | null;
  asset: ShotAssetDetail | null;
  clip: ShotClipDetail | null;
}

/** P3b: one parallax plane on `/progress`. `null` for `ShotProgress.layers`
 * means the shot has no plane slots (matching `secondary`); a list means
 * render one upload slot per entry posting `panel=layer:${index}`.
 * `prompt` is already `layer_styled_prompt` — copy it, do not restyle.
 * Layers are clips not assets (`asset` stays null; P1 stores overrides
 * as `GeneratedClip` under `layer_prompt_hash`). */
export interface ShotLayerPanel {
  index: number;
  role: string;
  prompt: string;
  state: ShotBindingState | null;
  last_error: string | null;
  asset: ShotAssetDetail | null;
  clip: ShotClipDetail | null;
}

/** Shared by api + gate: primary/secondary plus index-form layer planes
 * (`layer:0` / `layer:1`). Backend `_parse_override_panel` accepts these. */
export type OverridePanel = "primary" | "secondary" | `layer:${number}`;

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
  // Emitted for every shot (backend `_shot_progress_entry`) — the field
  // this payload was missing entirely before P3a, so nothing here could
  // even say a shot was `split_frame`.
  camera_movement: string;
  secondary: ShotSecondaryPanel | null;
  // P3b: `null` when the shot has no planes; a list (index order) when
  // it does. Existence of the list is the gate's single signal for
  // plane slots — same idiom as `secondary != null`.
  layers: ShotLayerPanel[] | null;
  // gate_panel_overrides.md §7.5 addendum, 2026-09-13 CORRECTION: "can
  // this shot be approved", computed server-side by the SAME predicate
  // the approval guard uses (`_shot_is_filled`, app/api/projects.py) -
  // never re-derive this from `state`/`layers` here, that would be a
  // fourth copy of the same question (the first correction already
  // found three disagreeing). `state` above stays the honest raw
  // binding state (still used for "still searching"/"headed for
  // generation" labelling on the primary panel) - a layered shot with
  // every plane resolved can report `filled: true` while `state` still
  // reads `awaiting_generation` forever, because there is no per-layer
  // binding column (§2) for it to ever change.
  filled: boolean;
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

// POST/GET /shots/{id}/generate/video (ui_style_feature_coverage.md §3.7).
// `status` is API-facing: "pending" | "completed" | "failed".
export interface GenerateShotVideoResult {
  shot_id: string;
  clip_id: string;
  job_id: string | null;
  status: "pending" | "completed" | "failed" | string;
  error?: string | null;
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

// -- GET /projects/{id}/deletion-preview, DELETE /projects/{id} -------------
//
// Both endpoints return the identical shape (backend/app/schemas/
// project_deletion.py) - DELETE reports what it actually removed, which is
// exactly what the preview promised. `narration_dependencies`/
// `generated_clip_dependencies` are non-empty only when at least one OTHER
// project depends on media this project owns (the global content-hash/
// prompt-hash cache, backend/app/projects/deletion.py's own module
// docstring) - the confirmation dialog's warning hinges on these being
// non-empty, not on `affected_project_ids` alone (kept for convenience).

export interface NarrationDependency {
  narration_id: string;
  scene_id: string;
  content_hash: string;
  depended_on_by_project_id: string;
  depended_on_by_project_name: string;
  depended_on_by_scene_id: string;
  respend_estimate_cents: number;
}

export interface GeneratedClipDependency {
  clip_id: string;
  shot_id: string;
  prompt_hash: string;
  depended_on_by_project_id: string;
  depended_on_by_project_name: string;
  depended_on_by_shot_id: string;
  panel: "primary" | "secondary";
  respend_estimate_cents: number;
}

export interface ProjectDeletionSummary {
  project_id: string;
  project_name: string;
  row_counts: Record<string, number>;
  storage_path: string;
  storage_exists: boolean;
  storage_bytes: number;
  narration_dependencies: NarrationDependency[];
  generated_clip_dependencies: GeneratedClipDependency[];
  affected_project_ids: string[];
  total_respend_estimate_cents: number;
}
