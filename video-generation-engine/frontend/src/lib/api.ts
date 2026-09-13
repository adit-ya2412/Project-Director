import type {
  GenerateShotImageResult,
  GenerateShotVideoResult,
  MusicUploadResult,
  OverridePanel,
  Project,
  ProgressResponse,
  ProjectDeletionSummary,
  RegenerateFailedResult,
  SceneApprovalResult,
  ScriptPreflightResponse,
  ScriptRewriteResponse,
  SfxKind,
  ShotProgress,
  Timeline,
  UploadedAssetResult,
  WorkflowTriggerResult,
} from "./types";

/**
 * Base URL for the API. Defaults to a relative path so the SAME build
 * works in both:
 *  - production, where FastAPI serves the built static files and the API
 *    from one origin, so `/api/v1/...` is correct as-is;
 *  - dev, where Vite's dev server proxies `/api/*` to
 *    `http://127.0.0.1:8000` (see vite.config.ts) — CORS is also already
 *    configured backend-side, so `VITE_API_BASE` can point straight at the
 *    backend instead if the proxy is ever inconvenient.
 */
const API_BASE =
  (import.meta.env.VITE_API_BASE as string | undefined) ?? "/api/v1";

export class ApiError extends Error {
  status: number;
  detail: unknown;

  constructor(status: number, detail: unknown) {
    super(
      typeof detail === "string"
        ? detail
        : `request failed with status ${status}`,
    );
    this.status = status;
    this.detail = detail;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers:
      init?.body && !(init.body instanceof FormData)
        ? { "Content-Type": "application/json", ...(init.headers ?? {}) }
        : init?.headers,
    ...init,
  });
  if (!res.ok) {
    let detail: unknown;
    try {
      const body = await res.json();
      detail = body?.detail ?? body;
    } catch {
      detail = await res.text().catch(() => res.statusText);
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

// -- Projects -----------------------------------------------------------

export function listProjects(): Promise<Project[]> {
  return request("/projects");
}

export function getProject(projectId: string): Promise<Project> {
  return request(`/projects/${projectId}`);
}

/** What deleting this project would destroy, AND what it would cost other
 * projects still sharing its cached narration/generated media (global
 * content-hash cache - `backend/app/projects/deletion.py`'s own module
 * docstring). Read-only, safe to call repeatedly - the confirmation dialog
 * calls this before ever showing a "delete" button as enabled. */
export function getDeletionPreview(
  projectId: string,
): Promise<ProjectDeletionSummary> {
  return request(`/projects/${projectId}/deletion-preview`);
}

/** Actually deletes the project: every DB row (verified FK-safe order) and
 * its storage directory. Returns the same shape `getDeletionPreview`
 * already showed the caller - what was actually removed. Only ever call
 * this after the caller has shown the preview and gotten explicit human
 * confirmation - there is no undo. */
export function deleteProject(
  projectId: string,
): Promise<ProjectDeletionSummary> {
  return request(`/projects/${projectId}`, { method: "DELETE" });
}

export function createProject(
  name: string,
  opts?: {
    render_style?: string | null;
    frame_aspect?: string | null;
    language_code?: string | null;
  },
): Promise<Project> {
  return request("/projects", {
    method: "POST",
    body: JSON.stringify({
      name,
      ...(opts?.render_style ? { render_style: opts.render_style } : {}),
      ...(opts?.frame_aspect ? { frame_aspect: opts.frame_aspect } : {}),
      ...(opts?.language_code ? { language_code: opts.language_code } : {}),
    }),
  });
}

export function uploadScript(
  projectId: string,
  content: string,
): Promise<Project> {
  return request(`/projects/${projectId}/script`, {
    method: "POST",
    body: JSON.stringify({ content }),
  });
}

export function setRenderStyle(
  projectId: string,
  renderStyle: string,
  frameAspect?: string | null,
): Promise<Project> {
  return request(`/projects/${projectId}/style`, {
    method: "POST",
    body: JSON.stringify({
      render_style: renderStyle,
      frame_aspect: frameAspect ?? null,
    }),
  });
}

export function setLanguage(
  projectId: string,
  languageCode: string | null,
): Promise<Project> {
  return request(`/projects/${projectId}/language`, {
    method: "POST",
    body: JSON.stringify({ language_code: languageCode }),
  });
}

/** POST /grade — records an override (or `null` to clear it). Does NOT
 * re-render; the caller still has to hit `/render/only`. Same shape as
 * `setRenderStyle`, returns the new Timeline (not a workflow trigger). */
export function setGrade(
  projectId: string,
  gradeStyle: string | null,
): Promise<Timeline> {
  return request(`/projects/${projectId}/grade`, {
    method: "POST",
    body: JSON.stringify({ grade_style: gradeStyle }),
  });
}

export function preflightScript(
  projectId: string,
  script: string,
  style: string,
): Promise<ScriptPreflightResponse> {
  return request(`/projects/${projectId}/script/preflight`, {
    method: "POST",
    body: JSON.stringify({ script, style }),
  });
}

export function rewriteScript(
  projectId: string,
  script: string,
  style: string,
  persist = false,
): Promise<ScriptRewriteResponse> {
  return request(`/projects/${projectId}/script/rewrite`, {
    method: "POST",
    body: JSON.stringify({ script, style, persist }),
  });
}

export interface AssetUpload {
  file: File;
  description: string;
}

export function uploadAssets(
  projectId: string,
  uploads: AssetUpload[],
): Promise<UploadedAssetResult[]> {
  const form = new FormData();
  for (const u of uploads) {
    form.append("files", u.file);
    form.append("descriptions", u.description);
  }
  return request(`/projects/${projectId}/assets`, {
    method: "POST",
    body: form,
  });
}

// -- Timeline -------------------------------------------------------------

export function getTimeline(projectId: string): Promise<Timeline> {
  return request(`/projects/${projectId}/timeline`);
}

export function approveTimeline(
  projectId: string,
  confirmedCostCents?: number,
): Promise<WorkflowTriggerResult> {
  const q =
    confirmedCostCents == null
      ? ""
      : `?confirmed_cost_cents=${confirmedCostCents}`;
  return request(`/projects/${projectId}/timeline/approve${q}`, {
    method: "POST",
  });
}

export function approveScene(
  projectId: string,
  sceneId: string,
): Promise<SceneApprovalResult> {
  return request(`/projects/${projectId}/scenes/${sceneId}/approve`, {
    method: "POST",
  });
}

export function regenerateFailedInScene(
  projectId: string,
  sceneId: string,
  confirmedCostCents: number,
): Promise<RegenerateFailedResult> {
  return request(
    `/projects/${projectId}/scenes/${sceneId}/regenerate-failed?confirmed_cost_cents=${confirmedCostCents}`,
    { method: "POST" },
  );
}

// -- Progress ---------------------------------------------------------------

const progressCache = new Map<
  string,
  { etag: string; body: ProgressResponse }
>();

export async function getProgress(
  projectId: string,
  opts?: { expandShots?: boolean },
): Promise<ProgressResponse> {
  const q = opts?.expandShots ? "?expand=shots" : "";
  const key = `${projectId}:${q}`;
  const cached = progressCache.get(key);
  const headers: Record<string, string> = {};
  if (cached?.etag) headers["If-None-Match"] = cached.etag;
  const res = await fetch(`${API_BASE}/projects/${projectId}/progress${q}`, {
    headers,
    cache: "no-store",
  });
  if (res.status === 304 && cached) return cached.body;
  if (!res.ok) {
    let detail: unknown;
    try {
      const body = await res.json();
      detail = body?.detail ?? body;
    } catch {
      detail = await res.text().catch(() => res.statusText);
    }
    throw new ApiError(res.status, detail);
  }
  const body = (await res.json()) as ProgressResponse;
  const etag = res.headers.get("ETag");
  if (etag) progressCache.set(key, { etag, body });
  return body;
}

// -- Prompt export (P0, gate_panel_overrides.md) --------------------------
//
// The user's real cost-saving workflow (§1 of the plan): copy a shot's
// prompt off this gate, generate it for free in a provider whose quota
// they already pay for (Grok), and upload the result via `overrideShot`
// instead of paying fal.ai per image. On a 41-shot film that was 61
// one-at-a-time copies, and the 20 parallax layer prompts were never shown
// here at all — this is the "every prompt, one action" escape hatch.
// Plain text, not JSON: the destination is a paste box in someone else's
// chat UI, never code (see `app/assets/prompt_export.py`'s own docstring).

/** Raw URL for the export, used directly as an `<a download>` target — the
 * browser's own save-file flow handles it, and the backend already sets
 * `Content-Disposition: attachment` so even a bare navigation downloads
 * rather than rendering a page of prompt text. */
export function promptExportUrl(projectId: string): string {
  return `${API_BASE}/projects/${projectId}/prompts/export`;
}

/** Same endpoint, fetched as text for the "copy everything" gesture — a
 * plain `<a>` can trigger a save-file dialog but cannot populate the
 * clipboard, so copying needs its own request. Not `request<T>()` above:
 * that helper always calls `res.json()`, and this response is
 * `text/plain`. */
export async function fetchPromptExportText(projectId: string): Promise<string> {
  const res = await fetch(`${API_BASE}/projects/${projectId}/prompts/export`);
  if (!res.ok) {
    let detail: unknown;
    try {
      const body = await res.json();
      detail = body?.detail ?? body;
    } catch {
      detail = await res.text().catch(() => res.statusText);
    }
    throw new ApiError(res.status, detail);
  }
  return res.text();
}

export function getSceneShots(
  projectId: string,
  sceneId: string,
): Promise<{ scene_id: string; shots: ShotProgress[] }> {
  return request(`/projects/${projectId}/scenes/${sceneId}/shots`);
}

// -- Triggers (long-running, 202 + a run id to poll — F0a landed. Callers
// must never block navigation/UI on these settling: fire the request and
// poll `getProgress` separately; the response is a run id, not the
// outcome.) ------------------------------------------------------------

export function renderProject(
  projectId: string,
): Promise<WorkflowTriggerResult> {
  return request(`/projects/${projectId}/render`, { method: "POST" });
}

/** R3: re-render only — structurally unable to reach a paid step. What the
 * result screen's free "re-render" action should call, never `renderProject`
 * (which is also allowed to advance narration/generation). */
export function renderOnly(projectId: string): Promise<WorkflowTriggerResult> {
  return request(`/projects/${projectId}/render/only`, { method: "POST" });
}

export function renderDraft(projectId: string): Promise<{
  project_id: string;
  timeline_version: number;
  draft_path: string;
  expired_drafts_purged: number;
}> {
  return request(`/projects/${projectId}/render/draft`, { method: "POST" });
}

// -- Human corrections --------------------------------------------------

/** P3a/P3b: `panel` defaults to `"primary"` so every call site that
 * predates split-screen / layer support keeps posting exactly where it
 * always did (no query). Non-primary → `?panel=...` for `secondary` and
 * `layer:N`. Backend `_parse_override_panel` 400s a panel the shot's
 * shape cannot accept, so a wrong caller finds out immediately. */
export function overrideShot(
  projectId: string,
  shotId: string,
  file: File,
  description?: string,
  panel: OverridePanel = "primary",
): Promise<WorkflowTriggerResult> {
  const form = new FormData();
  form.append("file", file);
  if (description) form.append("description", description);
  const q = panel === "primary" ? "" : `?panel=${panel}`;
  return request(`/projects/${projectId}/shots/${shotId}/override${q}`, {
    method: "POST",
    body: form,
  });
}

export function retryMusic(
  projectId: string,
  searchTerms?: string[],
): Promise<WorkflowTriggerResult> {
  return request(`/projects/${projectId}/music/retry`, {
    method: "POST",
    body: JSON.stringify(searchTerms ? { search_terms: searchTerms } : {}),
  });
}

/** C1 (analysis.md, decisions 6a/6b/7): replace the selected BGM with the
 * human's own file. Length never rejects - the response carries warnings
 * the caller should surface. `gainOffsetDb` rides on top of the style's
 * bed gain and is fingerprinted, so changing it forces a re-render. */
export function uploadMusic(
  projectId: string,
  file: File,
  gainOffsetDb?: number,
): Promise<MusicUploadResult> {
  const form = new FormData();
  form.append("file", file);
  if (gainOffsetDb != null && gainOffsetDb !== 0) {
    form.append("gain_offset_db", String(gainOffsetDb));
  }
  return request(`/projects/${projectId}/music/upload`, {
    method: "POST",
    body: form,
  });
}

export function retryNarration(
  projectId: string,
  voiceId: string,
): Promise<WorkflowTriggerResult> {
  return request(`/projects/${projectId}/narration/retry`, {
    method: "POST",
    body: JSON.stringify({ voice_id: voiceId }),
  });
}

/** C3f: replace one SFX kind's clip, or disable it (`enabled=false`,
 * no file). Exactly one of those two operations per call — the backend
 * 400s if both or neither are sent. */
export function overrideSfx(
  projectId: string,
  kind: SfxKind,
  opts: { file?: File; enabled?: boolean } = {},
): Promise<WorkflowTriggerResult> {
  const form = new FormData();
  if (opts.file) form.append("file", opts.file);
  if (opts.enabled === false) form.append("enabled", "false");
  return request(`/projects/${projectId}/sfx/${kind}/override`, {
    method: "POST",
    body: form,
  });
}

/** Undo for per-kind SFX override/disable — resets clips and re-runs
 * selection. Same 202-trigger shape as `retryMusic`. */
export function retrySfx(projectId: string): Promise<WorkflowTriggerResult> {
  return request(`/projects/${projectId}/sfx/retry`, { method: "POST" });
}

/** long_form_direction.md A12: veto one shot's planner-authored diegetic
 * SFX cue (`Shot.sfx_cue`) before the paid `generate_diegetic_sfx` step
 * spends on it. NOT `overrideSfx` — that endpoint 400s for
 * `kind=diegetic` by design (its one-clip-per-kind model does not apply
 * per-shot); this hits the narrow per-shot endpoint A12 added instead.
 * Means "no sound for this shot", never "regenerate" — there is no
 * corresponding "restore" call, matching the backend's own framing. */
export function clearShotSfxCue(
  projectId: string,
  shotId: string,
): Promise<WorkflowTriggerResult> {
  return request(`/projects/${projectId}/shots/${shotId}/sfx-cue/clear`, {
    method: "POST",
  });
}

/**
 * The one-gate redesign's Task 4: generate (or regenerate) one shot's
 * image on demand, at the single asset-review gate, before approval.
 * Deliberately synchronous on the backend (no `background_tasks`) so a
 * human can click this several times across several shots mid-review
 * without racing the workflow engine forward — unlike every function
 * above, this resolves to the real result, not a run id to poll.
 * `prompt` omitted (or unchanged) regenerates with the shot's existing
 * prompt; a different, non-blank value edits it first (recorded as its
 * own timeline version) and generates from the edit.
 */
export function generateShotImage(
  projectId: string,
  shotId: string,
  prompt?: string,
): Promise<GenerateShotImageResult> {
  return request(`/projects/${projectId}/shots/${shotId}/generate`, {
    method: "POST",
    body: JSON.stringify(prompt !== undefined ? { prompt } : {}),
  });
}

/** A6: submit (or join) a per-shot video generation job. 202 + pending;
 * poll `pollShotVideo` for the real outcome. Image-to-video — a still
 * must already exist. Not available under DRY_RUN. */
export function generateShotVideo(
  projectId: string,
  shotId: string,
): Promise<GenerateShotVideoResult> {
  return request(`/projects/${projectId}/shots/${shotId}/generate/video`, {
    method: "POST",
  });
}

export function pollShotVideo(
  projectId: string,
  shotId: string,
): Promise<GenerateShotVideoResult> {
  return request(`/projects/${projectId}/shots/${shotId}/generate/video`);
}

// -- Media (bytes) --------------------------------------------------------
//
// F0b, "landing shortly" per the task brief: neither of these two GETs
// exists on the backend yet (asset.local_path is a server filesystem path
// today, so nothing can currently display an image). Building against the
// agreed contract regardless — plain <img src=...> URLs, no fetch wrapper
// needed since these return raw bytes, not JSON.

/** P3a/P3b: `panel` defaults to `"primary"`, so the URL every existing
 * caller builds is byte-identical to before (no query). Non-primary →
 * `?panel=...` for `secondary` and `layer:N`. Still `Cache-Control:
 * no-cache` either way (see `get_shot_asset`'s own docstring) — an
 * override rebinds the SAME url to different bytes. */
export function shotAssetUrl(
  projectId: string,
  shotId: string,
  panel: OverridePanel = "primary",
): string {
  const q = panel === "primary" ? "" : `?panel=${panel}`;
  return `${API_BASE}/projects/${projectId}/shots/${shotId}/asset${q}`;
}

export function projectThumbnailUrl(projectId: string): string {
  return `${API_BASE}/projects/${projectId}/thumbnail`;
}

export function videoUrl(projectId: string): string {
  return `${API_BASE}/projects/${projectId}/video`;
}

export function draftVideoUrl(projectId: string): string {
  return `${API_BASE}/projects/${projectId}/video/draft`;
}

export function shotClipUrl(projectId: string, shotId: string): string {
  return `${API_BASE}/projects/${projectId}/shots/${shotId}/clip`;
}
