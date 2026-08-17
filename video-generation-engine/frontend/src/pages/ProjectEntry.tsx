import { Navigate, useParams } from 'react-router-dom'
import { useProject } from '@/lib/queries'
import type { ProjectStatus } from '@/lib/types'
import { Skeleton } from '@/components/ui/skeleton'

/** Bare `/projects/:id` is a landing pad: figure out which of the three
 * screens (progress / review / result) applies right now and redirect
 * there, so links from the project list and elsewhere don't need to know
 * the state machine themselves. `awaiting_review` shares the review
 * screen with `awaiting_approval` — under the one-gate redesign it's the
 * same screen's post-approval backstop, not a separate gate. */
function targetFor(status: ProjectStatus): string {
  switch (status) {
    case 'awaiting_approval':
    case 'awaiting_review':
      return 'review'
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
