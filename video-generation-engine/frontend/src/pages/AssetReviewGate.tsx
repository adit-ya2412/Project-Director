import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams, Link } from 'react-router-dom'
import { AlertTriangle, CheckCircle2, ImagePlus, Lock, RefreshCw, Sparkles } from 'lucide-react'
import {
  useProgress,
  useTimeline,
  useApproveTimeline,
  useOverrideShot,
  useGenerateShotImage,
} from '@/lib/queries'
import { shotAssetUrl, ApiError } from '@/lib/api'
import { formatCostCents, formatDuration } from '@/lib/format'
import { translateError } from '@/lib/errors'
import { shotAssetSource } from '@/lib/asset-source'
import { AssetSourceBadge } from '@/components/AssetSourceBadge'
import { ResolutionWarningBadge } from '@/components/ResolutionWarning'
import { computeResolutionWarning } from '@/lib/resolution'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Textarea } from '@/components/ui/textarea'
import { OverrideDialog } from '@/components/OverrideDialog'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog'
import { useToast } from '@/components/ui/toast'
import type { Camera, ShotProgress } from '@/lib/types'

// Mirrors `_TERMINAL_SHOT_STATES` in `app/api/projects.py` exactly — a
// shot counts as filled when search found it, a human overrode it, or it
// was generated (on demand here, or by the pipeline). Approval is blocked
// server-side until every shot is in one of these two states (Task 2 of
// the one-gate redesign), so the button below mirrors that check
// client-side rather than making a human discover it via a 400.
const TERMINAL_STATES = new Set(['resolved', 'generated'])

function isFilled(shot: ShotProgress): boolean {
  return TERMINAL_STATES.has(shot.state)
}

function GenerateDialog({
  shot,
  open,
  onOpenChange,
  onConfirm,
  isPending,
}: {
  shot: ShotProgress
  open: boolean
  onOpenChange: (open: boolean) => void
  onConfirm: (prompt: string) => void
  isPending: boolean
}) {
  const [prompt, setPrompt] = useState(shot.prompt)
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{shot.state === 'resolved' ? 'Edit prompt and generate' : 'Generate this shot'}</DialogTitle>
          <DialogDescription>
            The prompt is what the image is generated from — edit it if the last attempt (or the plan's own
            guess) produced the wrong picture. Generating creates a new image and adds to this project's spend,
            unless it's an exact repeat of a prompt already generated for this shot.
          </DialogDescription>
        </DialogHeader>
        <Textarea value={prompt} onChange={(e) => setPrompt(e.target.value)} className="min-h-[120px]" />
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button disabled={isPending || !prompt.trim()} onClick={() => onConfirm(prompt.trim())}>
            {isPending ? 'Generating…' : 'Generate (may cost money)'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function ShotImage({
  projectId,
  shot,
  camera,
  onExpand,
}: {
  projectId: string
  shot: ShotProgress
  camera: Camera | undefined
  onExpand: () => void
}) {
  const [errored, setErrored] = useState(false)
  const [naturalSize, setNaturalSize] = useState<{ width: number; height: number } | null>(null)
  const source = shotAssetSource(shot)
  const hasImage = (shot.asset || shot.clip) && !errored
  // `shotAssetUrl` is the same URL string before and after an
  // override/regenerate — an already-mounted `<img>` has no reason to
  // re-request it, so the browser just keeps showing the old bytes it
  // already painted (the backend's `Cache-Control: no-cache` only forces
  // revalidation on a NEW request; it does nothing if no request is ever
  // made). Keying on the bound asset/clip's own path forces React to
  // unmount and remount the element whenever the actual file changes.
  const mediaVersion = shot.asset?.local_path ?? shot.clip?.local_path ?? shot.state

  if (!hasImage) {
    return (
      <div className="flex aspect-[9/16] w-36 shrink-0 flex-col items-center justify-center gap-1.5 rounded-md border border-dashed border-warning/40 bg-warning/5 p-2 text-center">
        <Sparkles className="h-5 w-5 text-warning" />
        <span className="text-xs text-warning">
          {shot.state === 'pending' ? 'Still searching…' : 'No picture yet'}
        </span>
      </div>
    )
  }

  return (
    <div className="w-36 shrink-0 space-y-1">
      <button
        type="button"
        onClick={onExpand}
        className="block cursor-zoom-in rounded-md focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        aria-label="View larger image"
      >
        <img
          key={mediaVersion}
          src={shotAssetUrl(projectId, shot.shot_id)}
          alt=""
          className="aspect-[9/16] w-36 rounded-md border border-border object-cover transition-opacity hover:opacity-90"
          onError={() => setErrored(true)}
          onLoad={(e) => {
            const img = e.currentTarget
            setNaturalSize({ width: img.naturalWidth, height: img.naturalHeight })
          }}
        />
      </button>
      {source === 'uploaded' && naturalSize && (
        <ResolutionWarningBadge warning={computeResolutionWarning(naturalSize.width, naturalSize.height, camera)} />
      )}
    </div>
  )
}

function ImageLightbox({
  projectId,
  shot,
  open,
  onOpenChange,
}: {
  projectId: string
  shot: ShotProgress | null
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl border-none bg-transparent p-0 shadow-none">
        {shot && (
          <div className="space-y-2">
            <img
              key={shot.asset?.local_path ?? shot.clip?.local_path ?? shot.state}
              src={shotAssetUrl(projectId, shot.shot_id)}
              alt=""
              className="mx-auto max-h-[80vh] w-auto rounded-md border border-border object-contain"
            />
            <p className="rounded-md bg-background/90 p-2 text-center text-sm text-foreground">
              {shot.says ? `"${shot.says}"` : shot.intent}
            </p>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}

export function AssetReviewGate() {
  const { projectId } = useParams<{ projectId: string }>()
  const navigate = useNavigate()
  const { toast } = useToast()
  const { data: progress, isLoading } = useProgress(projectId)
  const { data: timeline } = useTimeline(projectId)
  const approveTimeline = useApproveTimeline(projectId ?? '')
  const overrideShot = useOverrideShot(projectId ?? '')
  const generateShot = useGenerateShotImage(projectId ?? '')
  const [overrideTarget, setOverrideTarget] = useState<ShotProgress | null>(null)
  const [generateTarget, setGenerateTarget] = useState<ShotProgress | null>(null)
  const [lightboxTarget, setLightboxTarget] = useState<ShotProgress | null>(null)

  const cameraByShot = useMemo(() => {
    const map = new Map<string, Camera>()
    if (timeline) {
      for (const scene of timeline.scenes) {
        for (const shot of scene.shots) map.set(shot.id, shot.camera)
      }
    }
    return map
  }, [timeline])

  // Complementary to `Progress.tsx`'s own redirect: clicking Approve fires
  // the mutation and navigates to `/progress` immediately (fire-and-forget,
  // per the trigger contract), but the very FIRST poll from there can
  // legitimately still read `workflow_state: "awaiting_approval"` for one
  // beat if it lands before the approve call has actually been processed
  // server-side — bouncing straight back here. Without this effect,
  // nothing then ever notices the workflow has since moved on (this page
  // only reacts to props/queries, it never re-checks on its own), so a
  // human could be stuck looking at a stale review gate for an entire
  // render. This self-corrects within one more poll cycle instead.
  useEffect(() => {
    if (!progress || !projectId) return
    if (progress.workflow_state === 'completed') {
      navigate(`/projects/${projectId}/result`, { replace: true })
    } else if (
      progress.workflow_state &&
      progress.workflow_state !== 'awaiting_approval' &&
      progress.workflow_state !== 'awaiting_review'
    ) {
      navigate(`/projects/${projectId}/progress`, { replace: true })
    }
  }, [progress, projectId, navigate])

  if (isLoading || !progress || !projectId) {
    return (
      <div className="mx-auto max-w-4xl space-y-3">
        <Skeleton className="h-8 w-64" />
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-32 w-full" />
        ))}
      </div>
    )
  }

  // Once the plan is already approved, `AwaitReviewStep`'s backstop is why
  // we're here — the pipeline paused only because some shot ended
  // `failed` after approval. There is nothing left to "approve" (that
  // already happened), and no separate "continue" button: fixing the
  // shot (override or generate) already resumes the workflow on its own.
  //
  // Deliberately `workflow_state`, not `progress.status`: nothing resets
  // `project.status` away from AWAITING_REVIEW when a fix resumes the
  // workflow (only a later terminal state like COMPLETED overwrites it),
  // so it would keep reporting the backstop for the entire
  // resolve_assets_generate/render window that follows a fix — hiding the
  // Approve button and filtering to failed-only shots long after there
  // are none left. `workflow_state` correctly flips back to "running" the
  // instant the resume begins (same fix as `Progress.tsx`'s redirect).
  const isBackstop = progress.workflow_state === 'awaiting_review'
  const visibleShots = isBackstop ? progress.shots.filter((s) => s.state === 'failed') : progress.shots
  const unfilledShots = progress.shots.filter((s) => !isFilled(s))
  const canApprove = unfilledShots.length === 0

  function handleApprove() {
    approveTimeline.mutate(undefined, {
      onError: (err) =>
        toast({
          title: 'Could not approve',
          description: err instanceof ApiError ? String(err.detail) : 'Try again.',
          variant: 'destructive',
        }),
    })
    toast({ title: 'Approved', description: 'Moving on to narration and generation.' })
    navigate(`/projects/${projectId}/progress`)
  }

  function handleOverrideSubmit(shotId: string, file: File, description: string) {
    overrideShot.mutate(
      { shotId, file, description: description || undefined },
      {
        onSuccess: () => {
          toast({ title: 'Image saved', description: 'This shot is locked to your image.', variant: 'success' })
          setOverrideTarget(null)
        },
        onError: (err) =>
          toast({
            title: 'Could not save image',
            description: err instanceof ApiError ? String(err.detail) : 'Try again.',
            variant: 'destructive',
          }),
      },
    )
  }

  function handleGenerateConfirm(shot: ShotProgress, prompt: string) {
    generateShot.mutate(
      { shotId: shot.shot_id, prompt: prompt !== shot.prompt ? prompt : undefined },
      {
        onSuccess: (result) => {
          toast({
            title: 'Generated',
            description: result.cache_hit
              ? 'Reused an image already generated for this exact prompt — free.'
              : `Cost: ${formatCostCents(result.cost_cents)}`,
            variant: 'success',
          })
          setGenerateTarget(null)
        },
        onError: (err) =>
          toast({
            title: 'Could not generate',
            description: err instanceof ApiError ? String(err.detail) : 'Try again.',
            variant: 'destructive',
          }),
      },
    )
  }

  return (
    <div className="mx-auto max-w-4xl space-y-4">
      <div className="sticky top-14 z-30 -mx-4 flex flex-wrap items-center justify-between gap-3 border-b border-border bg-background/95 px-4 py-3 backdrop-blur">
        <div>
          <h1 className="text-lg font-semibold">{isBackstop ? 'Fix what failed' : 'Review the pictures'}</h1>
          <p className="text-sm text-muted-foreground">
            {isBackstop ? (
              <>
                {visibleShots.length} shot{visibleShots.length === 1 ? '' : 's'} need
                {visibleShots.length === 1 ? 's' : ''} a fix before the video can finish
              </>
            ) : (
              <>
                {progress.total_shots} shots · {unfilledShots.length} still{' '}
                {unfilledShots.length === 1 ? 'needs' : 'need'} a picture ·{' '}
                <span className="font-medium text-success">{formatCostCents(progress.spent_cost_cents)} spent so far</span>
                {progress.estimated_cost_cents > 0 && (
                  <> · ≈ {formatCostCents(progress.estimated_cost_cents)} to fill the rest</>
                )}
              </>
            )}
          </p>
        </div>
        {!isBackstop && (
          <Button size="lg" onClick={handleApprove} disabled={!canApprove}>
            <CheckCircle2 className="h-4 w-4" />
            Approve and continue
          </Button>
        )}
      </div>

      {!isBackstop && unfilledShots.length > 0 && (
        <Card className="border-warning/30 bg-warning/5 p-3 text-sm">
          <span className="font-medium text-warning">
            {unfilledShots.length} shot{unfilledShots.length === 1 ? '' : 's'} still {unfilledShots.length === 1 ? 'needs' : 'need'} a picture
          </span>{' '}
          <span className="text-muted-foreground">
            before you can approve. Upload your own image, or generate one now, for each one below.
          </span>
        </Card>
      )}

      <ul className="space-y-3">
        {visibleShots.map((shot) => {
          const source = shotAssetSource(shot)
          const flag = translateError(shot.last_error)
          const filled = isFilled(shot)
          return (
            <li key={shot.shot_id}>
              <Card className="flex gap-4 p-3">
                <ShotImage
                  projectId={projectId}
                  shot={shot}
                  camera={cameraByShot.get(shot.shot_id)}
                  onExpand={() => setLightboxTarget(shot)}
                />
                <div className="min-w-0 flex-1 space-y-1.5">
                  <div className="flex flex-wrap items-center gap-2">
                    {filled && <AssetSourceBadge source={source} />}
                    {!filled && shot.state !== 'failed' && (
                      <span className="inline-flex items-center gap-1 rounded-full border border-warning/30 bg-warning/10 px-2 py-0.5 text-xs font-medium text-warning">
                        {shot.state === 'pending' ? 'Still searching' : 'Headed for generation'}
                      </span>
                    )}
                    {shot.locked && (
                      <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
                        <Lock className="h-3 w-3" /> Locked by you
                      </span>
                    )}
                    <span className="text-xs text-muted-foreground">
                      {formatDuration(shot.starts_at_s)}–{formatDuration((shot.starts_at_s ?? 0) + shot.duration_s)}
                      {' '}({shot.duration_s.toFixed(1)}s)
                    </span>
                  </div>
                  {shot.says && <p className="text-sm text-foreground">"{shot.says}"</p>}
                  <p className="text-xs text-muted-foreground">
                    <span className="font-medium">{shot.intent}</span> — {shot.prompt}
                  </p>

                  {flag && (
                    <div className="flex items-start gap-2 rounded-md border border-warning/30 bg-warning/10 p-2 text-xs text-warning-foreground/90">
                      <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warning" />
                      <span>{flag.headline}</span>
                    </div>
                  )}

                  <div className="flex flex-wrap gap-2 pt-1">
                    <Button variant="outline" size="sm" onClick={() => setOverrideTarget(shot)}>
                      <ImagePlus className="h-3.5 w-3.5" />
                      {filled ? 'Replace image' : 'Upload your own'}
                    </Button>
                    <Button variant="outline" size="sm" onClick={() => setGenerateTarget(shot)}>
                      <RefreshCw className="h-3.5 w-3.5" />
                      {filled ? 'Edit prompt & regenerate' : 'Generate now'}
                    </Button>
                  </div>
                </div>
              </Card>
            </li>
          )
        })}
      </ul>

      {!isBackstop && (
        <div className="flex justify-end border-t border-border pt-4">
          <Button size="lg" onClick={handleApprove} disabled={!canApprove}>
            <CheckCircle2 className="h-4 w-4" />
            Approve and continue
          </Button>
        </div>
      )}

      {overrideTarget && (
        <OverrideDialog
          open={!!overrideTarget}
          onOpenChange={(o) => !o && setOverrideTarget(null)}
          title="Supply this shot's image"
          description={
            isFilled(overrideTarget)
              ? "This replaces the current image. It's free and instant."
              : 'This locks the shot to your image — generation never runs for it, so it costs nothing.'
          }
          camera={cameraByShot.get(overrideTarget.shot_id)}
          isPending={overrideShot.isPending}
          onSubmit={(file, description) => handleOverrideSubmit(overrideTarget.shot_id, file, description)}
        />
      )}

      {generateTarget && (
        <GenerateDialog
          shot={generateTarget}
          open={!!generateTarget}
          onOpenChange={(o) => !o && setGenerateTarget(null)}
          isPending={generateShot.isPending}
          onConfirm={(prompt) => handleGenerateConfirm(generateTarget, prompt)}
        />
      )}

      <ImageLightbox
        projectId={projectId}
        shot={lightboxTarget}
        open={!!lightboxTarget}
        onOpenChange={(o) => !o && setLightboxTarget(null)}
      />

      <p className="pb-6 text-center">
        <Link to="/" className="text-sm text-muted-foreground hover:text-foreground">
          Back to projects
        </Link>
      </p>
    </div>
  )
}
