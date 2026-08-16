import { Navigate, useParams } from 'react-router-dom'
import { useProject } from '@/lib/queries'
import type { ProjectStatus } from '@/lib/types'
import { Skeleton } from '@/components/ui/skeleton'

/** Bare `/projects/:id` is a landing pad: figure out which of the four
 * screens (progress / gate 1 / gate 2 / result) applies right now and
 * redirect there, so links from the project list and elsewhere don't need
 * to know the state machine themselves. */
function targetFor(status: ProjectStatus): string {
  switch (status) {
    case 'awaiting_approval':
      return 'review'
    case 'awaiting_review':
      return 'generated-review'
    case 'completed':
      return 'result'
    case 'created':
    case 'script_uploaded':
    case 'rendering':
    case 'failed':
    default:
      return 'progress'
  }
}

export function ProjectEntry() {
  const { projectId } = useParams<{ projectId: string }>()
  const { data: project, isLoading, isError } = useProject(projectId)

  if (isLoading) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-40 w-full" />
      </div>
    )
  }
  if (isError || !project) {
    return <p className="text-sm text-muted-foreground">Project not found.</p>
  }

  return <Navigate replace to={`/projects/${project.id}/${targetFor(project.status)}`} />
}
