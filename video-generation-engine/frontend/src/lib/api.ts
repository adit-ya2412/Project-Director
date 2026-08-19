import type {
  GenerateShotImageResult,
  Project,
  ProgressResponse,
  RegenerateFailedResult,
  SceneApprovalResult,
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

export function createProject(name: string): Promise<Project> {
  return request("/projects", {
    method: "POST",
    body: JSON.stringify({ name }),
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

export function overrideShot(
  projectId: string,
  shotId: string,
  file: File,
  description?: string,
): Promise<WorkflowTriggerResult> {
  const form = new FormData();
  form.append("file", file);
  if (description) form.append("description", description);
  return request(`/projects/${projectId}/shots/${shotId}/override`, {
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

export function retryNarration(
  projectId: string,
  voiceId: string,
): Promise<WorkflowTriggerResult> {
  return request(`/projects/${projectId}/narration/retry`, {
    method: "POST",
    body: JSON.stringify({ voice_id: voiceId }),
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

// -- Media (bytes) --------------------------------------------------------
//
// F0b, "landing shortly" per the task brief: neither of these two GETs
// exists on the backend yet (asset.local_path is a server filesystem path
// today, so nothing can currently display an image). Building against the
// agreed contract regardless — plain <img src=...> URLs, no fetch wrapper
// needed since these return raw bytes, not JSON.

export function shotAssetUrl(projectId: string, shotId: string): string {
  return `${API_BASE}/projects/${projectId}/shots/${shotId}/asset`;
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
