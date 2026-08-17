import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import * as api from './api'

// Per F3: "polling every 2-3s is ample; individual planner stages take
// tens of seconds." Used for both the progress screen and the two review
// gates, which are really progress-screen-adjacent views of the same data.
const PROGRESS_POLL_MS = 2500

export const qk = {
  projects: ['projects'] as const,
  project: (id: string) => ['project', id] as const,
  progress: (id: string) => ['progress', id] as const,
  timeline: (id: string) => ['timeline', id] as const,
}

export function useProjects() {
  return useQuery({
    queryKey: qk.projects,
    queryFn: api.listProjects,
    // The project list is where failed/stuck projects surface (F1) - a
    // moderate poll keeps status chips fresh without hammering the API.
    refetchInterval: 5000,
  })
}

export function useProject(projectId: string | undefined) {
  return useQuery({
    queryKey: qk.project(projectId ?? ''),
    queryFn: () => api.getProject(projectId as string),
    enabled: !!projectId,
    // Without this, a trigger mutation's one-time invalidation on
    // settlement is the ONLY refetch this query ever gets - which fires
    // immediately (long before a retry's re-render actually finishes),
    // so `project.updated_at` (what Result.tsx keys its `<video>` on to
    // detect a new render) never updates again while the page stays
    // open. This is exactly why only a hard refresh surfaced a
    // re-rendered video - a hard refresh rebuilds the query cache from
    // scratch instead of relying on a stale one-shot fetch.
    refetchInterval: PROGRESS_POLL_MS,
  })
}

export function useProgress(projectId: string | undefined, opts?: { enabled?: boolean }) {
  return useQuery({
    queryKey: qk.progress(projectId ?? ''),
    queryFn: () => api.getProgress(projectId as string),
    enabled: !!projectId && (opts?.enabled ?? true),
    refetchInterval: PROGRESS_POLL_MS,
  })
}

export function useTimeline(projectId: string | undefined, opts?: { enabled?: boolean }) {
  return useQuery({
    queryKey: qk.timeline(projectId ?? ''),
    queryFn: () => api.getTimeline(projectId as string),
    enabled: !!projectId && (opts?.enabled ?? true),
  })
}

export function useCreateProject() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (name: string) => api.createProject(name),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.projects }),
  })
}

export function useUploadScript(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (content: string) => api.uploadScript(projectId, content),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.project(projectId) }),
  })
}

export function useUploadAssets(projectId: string) {
  return useMutation({
    mutationFn: (uploads: api.AssetUpload[]) => api.uploadAssets(projectId, uploads),
  })
}

/**
 * Every trigger mutation below shares one shape, per the task brief:
 * "the trigger endpoints will return 202 + a run id instead of blocking,
 * so poll /progress — never await a trigger." Concretely that means
 * callers should invoke `.mutate(...)` (fire-and-forget) and navigate or
 * update UI state immediately, relying on `useProgress`'s own poll to
 * reflect what happened — never `await mutateAsync(...)` before deciding
 * what the screen shows next. `onSettled` still refreshes the cache once
 * the request does resolve, for whenever that turns out to be.
 */
function invalidateAfterTrigger(qc: ReturnType<typeof useQueryClient>, projectId: string) {
  qc.invalidateQueries({ queryKey: qk.progress(projectId) })
  qc.invalidateQueries({ queryKey: qk.project(projectId) })
  qc.invalidateQueries({ queryKey: qk.timeline(projectId) })
}

export function useApproveTimeline(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => api.approveTimeline(projectId),
    onSettled: () => invalidateAfterTrigger(qc, projectId),
  })
}

export function useOverrideShot(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({
      shotId,
      file,
      description,
    }: {
      shotId: string
      file: File
      description?: string
    }) => api.overrideShot(projectId, shotId, file, description),
    onSettled: () => invalidateAfterTrigger(qc, projectId),
  })
}

export function useRetryMusic(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (searchTerms?: string[]) => api.retryMusic(projectId, searchTerms),
    onSettled: () => invalidateAfterTrigger(qc, projectId),
  })
}

export function useRetryNarration(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (voiceId: string) => api.retryNarration(projectId, voiceId),
    onSettled: () => invalidateAfterTrigger(qc, projectId),
  })
}

export function useRenderProject(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => api.renderProject(projectId),
    onSettled: () => invalidateAfterTrigger(qc, projectId),
  })
}

/** R3: the free re-render-only trigger — what the result screen's
 * "re-render" action should use, never `useRenderProject`. */
export function useRenderOnly(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => api.renderOnly(projectId),
    onSettled: () => invalidateAfterTrigger(qc, projectId),
  })
}

export function useRenderDraft(projectId: string) {
  return useMutation({
    mutationFn: () => api.renderDraft(projectId),
  })
}

/** Deliberately NOT `onSettled`-only like the triggers above: `/generate`
 * is synchronous and resolves to a real result (`cost_cents`, `cache_hit`)
 * worth reading directly in the caller's `onSuccess`. */
export function useGenerateShotImage(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ shotId, prompt }: { shotId: string; prompt?: string }) =>
      api.generateShotImage(projectId, shotId, prompt),
    onSettled: () => invalidateAfterTrigger(qc, projectId),
  })
}
