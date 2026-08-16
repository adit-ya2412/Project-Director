import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Film, Clock3, CalendarDays, ImageOff } from 'lucide-react'
import { useProjects } from '@/lib/queries'
import { projectThumbnailUrl } from '@/lib/api'
import { formatDate, formatDuration } from '@/lib/format'
import type { Project, ProjectStatus } from '@/lib/types'
import { StatusChip } from '@/components/StatusChip'
import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

// F1: "Failed projects are listed prominently, not hidden" — every dead
// end during real testing was something the user needed to see and act
// on. Sorting failures and other needs-attention statuses to the front is
// the concrete form of "prominent" (never filtered out, never buried
// below a long tail of finished projects).
const STATUS_PRIORITY: Record<ProjectStatus, number> = {
  failed: 0,
  awaiting_review: 1,
  awaiting_approval: 2,
  rendering: 3,
  script_uploaded: 4,
  created: 4,
  completed: 5,
}

function sortProjects(projects: Project[]): Project[] {
  return [...projects].sort((a, b) => {
    const pa = STATUS_PRIORITY[a.status] ?? 9
    const pb = STATUS_PRIORITY[b.status] ?? 9
    if (pa !== pb) return pa - pb
    return new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
  })
}

function ThumbnailImg({ project }: { project: Project }) {
  const [failed, setFailed] = useState(false)
  if (failed) {
    return (
      <div className="flex h-full w-full flex-col items-center justify-center gap-1 bg-secondary/50 text-muted-foreground">
        <ImageOff className="h-6 w-6" />
        <StatusChip status={project.status} />
      </div>
    )
  }
  return (
    <img
      src={projectThumbnailUrl(project.id)}
      alt=""
      className="h-full w-full object-cover"
      onError={() => setFailed(true)}
    />
  )
}

function ProjectCard({ project }: { project: Project }) {
  const shotCount = project.timeline?.scenes.reduce((n, s) => n + s.shots.length, 0) ?? null
  const duration = project.timeline?.metadata.total_duration_s ?? null
  const isFailed = project.status === 'failed'

  return (
    <Link to={`/projects/${project.id}`}>
      <Card
        className={cn(
          'group overflow-hidden transition-colors hover:border-primary/50',
          isFailed && 'border-destructive/50 bg-destructive/[0.04]',
        )}
      >
        <div className="aspect-[9/16] w-full max-h-56 overflow-hidden bg-secondary/40">
          <ThumbnailImg project={project} />
        </div>
        <div className="space-y-2 p-3">
          <div className="flex items-start justify-between gap-2">
            <h3 className="line-clamp-2 text-sm font-semibold">{project.name}</h3>
          </div>
          <StatusChip status={project.status} />
          {isFailed && project.error && (
            <p className="line-clamp-2 text-xs text-destructive-foreground/80">{project.error}</p>
          )}
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
            <span className="flex items-center gap-1">
              <Film className="h-3 w-3" />
              {shotCount != null ? `${shotCount} shot${shotCount === 1 ? '' : 's'}` : '—'}
            </span>
            <span className="flex items-center gap-1">
              <Clock3 className="h-3 w-3" />
              {duration != null ? formatDuration(duration) : '—'}
            </span>
            <span className="flex items-center gap-1">
              <CalendarDays className="h-3 w-3" />
              {formatDate(project.created_at)}
            </span>
          </div>
        </div>
      </Card>
    </Link>
  )
}

export function ProjectList() {
  const { data: projects, isLoading, isError, error } = useProjects()

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">Projects</h1>
          <p className="text-sm text-muted-foreground">Every project this instance has ever generated.</p>
        </div>
        <Button asChild>
          <Link to="/new">New project</Link>
        </Button>
      </div>

      {isLoading && (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
          {Array.from({ length: 10 }).map((_, i) => (
            <Skeleton key={i} className="aspect-[9/16] max-h-56 w-full" />
          ))}
        </div>
      )}

      {isError && (
        <Card className="border-destructive/40 p-4 text-sm text-destructive-foreground">
          Could not load projects: {error instanceof Error ? error.message : 'unknown error'}
        </Card>
      )}

      {!isLoading && !isError && projects && projects.length === 0 && (
        <Card className="p-10 text-center">
          <p className="text-muted-foreground">No projects yet.</p>
          <Button asChild className="mt-4">
            <Link to="/new">Create your first project</Link>
          </Button>
        </Card>
      )}

      {!isLoading && !isError && projects && projects.length > 0 && (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
          {sortProjects(projects).map((p) => (
            <ProjectCard key={p.id} project={p} />
          ))}
        </div>
      )}
    </div>
  )
}
