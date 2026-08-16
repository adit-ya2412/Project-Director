import { useMemo, useState } from 'react'
import { useNavigate, useParams, Link } from 'react-router-dom'
import { AlertTriangle, ImagePlus, RefreshCw, CheckCircle2, ArrowRight } from 'lucide-react'
import {
  useProgress,
  useTimeline,
  useOverrideShot,
  useRegenerateShot,
  useRenderProject,
} from '@/lib/queries'
import { shotAssetUrl } from '@/lib/api'
import { formatDuration } from '@/lib/format'
import { translateError } from '@/lib/errors'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { Skeleton } from '@/components/ui/skeleton'
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
import { ApiError } from '@/lib/api'
import type { Camera, ShotProgress } from '@/lib/types'

function RegenerateDialog({
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
          <DialogTitle>Edit prompt and regenerate</DialogTitle>
          <DialogDescription>
            The prompt is what produced this picture — rewriting it beats re-rolling the same dice. Regenerating
            creates a new image and adds to this project's spend.
          </DialogDescription>
        </DialogHeader>
        <Textarea value={prompt} onChange={(e) => setPrompt(e.target.value)} className="min-h-[120px]" />
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button disabled={isPending || !prompt.trim()} onClick={() => onConfirm(prompt.trim())}>
            {isPending ? 'Regenerating…' : 'Regenerate (costs money)'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export function Gate2GeneratedReview() {
  const { projectId } = useParams<{ projectId: string }>()
  const navigate = useNavigate()
  const { toast } = useToast()
  const { data: progress, isLoading } = useProgress(projectId)
  const { data: timeline } = useTimeline(projectId)
  const overrideShot = useOverrideShot(projectId ?? '')
  const regenerateShot = useRegenerateShot(projectId ?? '')
  const renderProject = useRenderProject(projectId ?? '')
  const [replaceTarget, setReplaceTarget] = useState<ShotProgress | null>(null)
  const [regenerateTarget, setRegenerateTarget] = useState<ShotProgress | null>(null)
  const [accepted, setAccepted] = useState<Set<string>>(new Set())

  const cameraByShot = useMemo(() => {
    const map = new Map<string, Camera>()
    if (timeline) {
      for (const scene of timeline.scenes) {
        for (const shot of scene.shots) map.set(shot.id, shot.camera)
      }
    }
    return map
  }, [timeline])

  const generatedShots = useMemo(
    () => (progress ? progress.shots.filter((s) => s.clip != null || s.state === 'failed') : []),
    [progress],
  )

  if (isLoading || !progress || !projectId) {
    return (
      <div className="mx-auto max-w-4xl space-y-3">
        <Skeleton className="h-8 w-64" />
        {Array.from({ length: 3 }).map((_, i) => (
          <Skeleton key={i} className="h-40 w-full" />
        ))}
      </div>
    )
  }

  const unresolvedFailures = generatedShots.filter((s) => s.state === 'failed').length

  function handleReplaceSubmit(shotId: string, file: File, description: string) {
    overrideShot.mutate(
      { shotId, file, description: description || undefined },
      {
        onSuccess: () => {
          toast({ title: 'Image replaced', variant: 'success' })
          setReplaceTarget(null)
        },
        onError: (err) =>
          toast({
            title: 'Could not replace image',
            description: err instanceof ApiError ? String(err.detail) : 'Try again.',
            variant: 'destructive',
          }),
      },
    )
  }

  function handleRegenerateConfirm(shotId: string, prompt: string) {
    regenerateShot.mutate(
      { shotId, prompt },
      {
        onSuccess: () => {
          toast({ title: 'Regenerating…', description: 'Poll progress for the new image.' })
          setRegenerateTarget(null)
        },
        onError: (err) => {
          const detail = err instanceof ApiError ? String(err.detail) : 'Try again.'
          toast({
            title: 'Could not regenerate',
            description:
              err instanceof ApiError && err.status === 404
                ? 'This backend build does not yet support per-shot regeneration with an edited prompt. Use "Replace" to upload an image instead.'
                : detail,
            variant: 'destructive',
          })
        },
      },
    )
  }

  function handleContinue() {
    renderProject.mutate()
    navigate(`/projects/${projectId}/progress`)
  }

  if (generatedShots.length === 0) {
    return (
      <div className="mx-auto max-w-2xl space-y-4 text-center">
        <p className="text-muted-foreground">No generated shots to review — every shot in this project came from a search or an upload.</p>
        <Button asChild variant="outline">
          <Link to={`/projects/${projectId}/progress`}>Back to progress</Link>
        </Button>
      </div>
    )
  }

  return (
    <div className="mx-auto max-w-4xl space-y-4">
      <div className="sticky top-14 z-30 -mx-4 flex flex-wrap items-center justify-between gap-3 border-b border-border bg-background/95 px-4 py-3 backdrop-blur">
        <div>
          <h1 className="text-lg font-semibold">Review generated images</h1>
          <p className="text-sm text-muted-foreground">
            {generatedShots.length} generated shot{generatedShots.length === 1 ? '' : 's'}
            {unresolvedFailures > 0 && (
              <span className="text-destructive"> · {unresolvedFailures} still need a fix</span>
            )}
          </p>
        </div>
        <Button size="lg" onClick={handleContinue} disabled={unresolvedFailures > 0}>
          Continue <ArrowRight className="h-4 w-4" />
        </Button>
      </div>

      {unresolvedFailures > 0 && (
        <Card className="border-destructive/40 bg-destructive/5 p-3 text-sm">
          The video can't finish while a shot has no usable image. Replace or regenerate the flagged shot
          {unresolvedFailures === 1 ? '' : 's'} below.
        </Card>
      )}

      <ul className="space-y-3">
        {generatedShots.map((shot) => {
          const flag = translateError(shot.last_error)
          const isAccepted = accepted.has(shot.shot_id)
          return (
            <li key={shot.shot_id}>
              <Card className="p-3">
                <CardContent className="flex gap-4 p-0">
                  <div className="w-40 shrink-0">
                    {shot.clip ? (
                      <img
                        src={shotAssetUrl(projectId, shot.shot_id)}
                        alt=""
                        className="aspect-[9/16] w-40 rounded-md border border-border object-cover"
                      />
                    ) : (
                      <div className="flex aspect-[9/16] w-40 items-center justify-center rounded-md border border-dashed border-destructive/40 bg-destructive/5 text-center text-xs text-destructive">
                        No usable image
                      </div>
                    )}
                  </div>
                  <div className="min-w-0 flex-1 space-y-2">
                    <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                      <span>
                        {formatDuration(shot.starts_at_s)}–{formatDuration((shot.starts_at_s ?? 0) + shot.duration_s)} ({shot.duration_s.toFixed(1)}s)
                      </span>
                    </div>
                    {shot.says && <p className="text-sm">"{shot.says}"</p>}

                    {flag && (
                      <div className="flex items-start gap-2 rounded-md border border-warning/30 bg-warning/10 p-2 text-xs text-warning-foreground/90">
                        <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warning" />
                        <span>{flag.headline}</span>
                      </div>
                    )}

                    <div className="flex flex-wrap gap-2 pt-1">
                      {shot.clip && !isAccepted && (
                        <Button
                          size="sm"
                          variant="secondary"
                          onClick={() => setAccepted((prev) => new Set(prev).add(shot.shot_id))}
                        >
                          <CheckCircle2 className="h-3.5 w-3.5" />
                          Looks good
                        </Button>
                      )}
                      {isAccepted && (
                        <span className="inline-flex items-center gap-1 text-xs text-success">
                          <CheckCircle2 className="h-3.5 w-3.5" /> Accepted
                        </span>
                      )}
                      <Button size="sm" variant="outline" onClick={() => setRegenerateTarget(shot)}>
                        <RefreshCw className="h-3.5 w-3.5" />
                        Edit prompt & regenerate
                      </Button>
                      <Button size="sm" variant="outline" onClick={() => setReplaceTarget(shot)}>
                        <ImagePlus className="h-3.5 w-3.5" />
                        Replace with my own image
                      </Button>
                    </div>
                  </div>
                </CardContent>
              </Card>
            </li>
          )
        })}
      </ul>

      <div className="flex justify-end border-t border-border pt-4">
        <Button size="lg" onClick={handleContinue} disabled={unresolvedFailures > 0}>
          Continue <ArrowRight className="h-4 w-4" />
        </Button>
      </div>

      {replaceTarget && (
        <OverrideDialog
          open={!!replaceTarget}
          onOpenChange={(o) => !o && setReplaceTarget(null)}
          title="Replace this shot's image"
          description="Free and instant — this locks the shot to your image and skips generation from now on."
          camera={cameraByShot.get(replaceTarget.shot_id)}
          isPending={overrideShot.isPending}
          onSubmit={(file, description) => handleReplaceSubmit(replaceTarget.shot_id, file, description)}
        />
      )}

      {regenerateTarget && (
        <RegenerateDialog
          shot={regenerateTarget}
          open={!!regenerateTarget}
          onOpenChange={(o) => !o && setRegenerateTarget(null)}
          isPending={regenerateShot.isPending}
          onConfirm={(prompt) => handleRegenerateConfirm(regenerateTarget.shot_id, prompt)}
        />
      )}

      <p className="pb-6 text-center">
        <Link to="/" className="text-sm text-muted-foreground hover:text-foreground">
          Back to projects
        </Link>
      </p>
    </div>
  )
}
