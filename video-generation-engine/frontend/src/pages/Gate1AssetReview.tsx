import { useMemo, useState } from 'react'
import { useNavigate, useParams, Link } from 'react-router-dom'
import { CheckCircle2, ImagePlus, Lock, Sparkles } from 'lucide-react'
import { useProgress, useTimeline, useApproveTimeline, useOverrideShot } from '@/lib/queries'
import { shotAssetUrl } from '@/lib/api'
import { formatCostCents, formatDuration } from '@/lib/format'
import { shotAssetSource } from '@/lib/asset-source'
import { AssetSourceBadge } from '@/components/AssetSourceBadge'
import { ResolutionWarningBadge } from '@/components/ResolutionWarning'
import { computeResolutionWarning } from '@/lib/resolution'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { OverrideDialog } from '@/components/OverrideDialog'
import { useToast } from '@/components/ui/toast'
import { ApiError } from '@/lib/api'
import type { Camera, ShotProgress } from '@/lib/types'

function ShotImage({
  projectId,
  shot,
  camera,
}: {
  projectId: string
  shot: ShotProgress
  camera: Camera | undefined
}) {
  const [errored, setErrored] = useState(false)
  const [naturalSize, setNaturalSize] = useState<{ width: number; height: number } | null>(null)
  const source = shotAssetSource(shot)

  if (shot.will_generate || (!shot.asset && !shot.clip) || errored) {
    return (
      <div className="flex aspect-[9/16] w-36 shrink-0 flex-col items-center justify-center gap-1.5 rounded-md border border-dashed border-warning/40 bg-warning/5 p-2 text-center">
        <Sparkles className="h-5 w-5 text-warning" />
        <span className="text-xs text-warning">Will be generated</span>
      </div>
    )
  }

  return (
    <div className="w-36 shrink-0 space-y-1">
      <img
        src={shotAssetUrl(projectId, shot.shot_id)}
        alt=""
        className="aspect-[9/16] w-36 rounded-md border border-border object-cover"
        onError={() => setErrored(true)}
        onLoad={(e) => {
          const img = e.currentTarget
          setNaturalSize({ width: img.naturalWidth, height: img.naturalHeight })
        }}
      />
      {source === 'uploaded' && naturalSize && (
        <ResolutionWarningBadge warning={computeResolutionWarning(naturalSize.width, naturalSize.height, camera)} />
      )}
    </div>
  )
}

export function Gate1AssetReview() {
  const { projectId } = useParams<{ projectId: string }>()
  const navigate = useNavigate()
  const { toast } = useToast()
  const { data: progress, isLoading } = useProgress(projectId)
  const { data: timeline } = useTimeline(projectId)
  const approveTimeline = useApproveTimeline(projectId ?? '')
  const overrideShot = useOverrideShot(projectId ?? '')
  const [overrideTarget, setOverrideTarget] = useState<ShotProgress | null>(null)

  const cameraByShot = useMemo(() => {
    const map = new Map<string, Camera>()
    if (timeline) {
      for (const scene of timeline.scenes) {
        for (const shot of scene.shots) map.set(shot.id, shot.camera)
      }
    }
    return map
  }, [timeline])

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

  const willGenerateCount = progress.shots.filter((s) => s.will_generate).length

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

  return (
    <div className="mx-auto max-w-4xl space-y-4">
      <div className="sticky top-14 z-30 -mx-4 flex flex-wrap items-center justify-between gap-3 border-b border-border bg-background/95 px-4 py-3 backdrop-blur">
        <div>
          <h1 className="text-lg font-semibold">Review the pictures</h1>
          <p className="text-sm text-muted-foreground">
            {progress.total_shots} shots · {willGenerateCount} headed for generation ·{' '}
            <span className="font-medium text-success">{formatCostCents(0)} spent so far</span>
          </p>
        </div>
        <Button size="lg" onClick={handleApprove}>
          <CheckCircle2 className="h-4 w-4" />
          Approve and continue
        </Button>
      </div>

      {willGenerateCount > 0 && (
        <Card className="border-warning/30 bg-warning/5 p-3 text-sm">
          <span className="font-medium text-warning">{willGenerateCount} shot{willGenerateCount === 1 ? '' : 's'} will be generated</span>{' '}
          <span className="text-muted-foreground">
            and cost money. Supply your own image for any of them below and generation never runs for that shot.
          </span>
        </Card>
      )}

      <ul className="space-y-3">
        {progress.shots.map((shot) => {
          const source = shotAssetSource(shot)
          return (
            <li key={shot.shot_id}>
              <Card className="flex gap-4 p-3">
                <ShotImage projectId={projectId} shot={shot} camera={cameraByShot.get(shot.shot_id)} />
                <div className="min-w-0 flex-1 space-y-1.5">
                  <div className="flex flex-wrap items-center gap-2">
                    {!shot.will_generate && <AssetSourceBadge source={source} />}
                    {shot.will_generate && (
                      <span className="inline-flex items-center gap-1 rounded-full border border-warning/30 bg-warning/10 px-2 py-0.5 text-xs font-medium text-warning">
                        Headed for generation
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
                  <Button variant="outline" size="sm" onClick={() => setOverrideTarget(shot)}>
                    <ImagePlus className="h-3.5 w-3.5" />
                    {shot.will_generate ? 'Supply an image' : 'Replace image'}
                  </Button>
                </div>
              </Card>
            </li>
          )
        })}
      </ul>

      <div className="flex justify-end border-t border-border pt-4">
        <Button size="lg" onClick={handleApprove}>
          <CheckCircle2 className="h-4 w-4" />
          Approve and continue
        </Button>
      </div>

      {overrideTarget && (
        <OverrideDialog
          open={!!overrideTarget}
          onOpenChange={(o) => !o && setOverrideTarget(null)}
          title="Supply this shot's image"
          description={
            overrideTarget.will_generate
              ? 'This locks the shot to your image — generation never runs for it, so it costs nothing.'
              : "This replaces the image the search found. Either way it's free and instant."
          }
          camera={cameraByShot.get(overrideTarget.shot_id)}
          isPending={overrideShot.isPending}
          onSubmit={(file, description) => handleOverrideSubmit(overrideTarget.shot_id, file, description)}
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
