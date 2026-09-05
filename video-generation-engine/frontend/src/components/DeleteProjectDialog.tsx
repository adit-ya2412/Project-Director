import { AlertTriangle } from 'lucide-react'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Alert, AlertTitle, AlertDescription } from '@/components/ui/alert'
import { Skeleton } from '@/components/ui/skeleton'
import { ErrorNotice } from '@/components/ErrorNotice'
import { useDeletionPreview, useDeleteProject } from '@/lib/queries'
import { formatBytes, formatCostCents } from '@/lib/format'

/**
 * Fetches `GET .../deletion-preview` the moment it opens (`enabled: open`)
 * and shows what it found before the "delete permanently" button is even
 * enabled - there is no path from "click delete" to an actual DELETE call
 * that skips seeing this first. The one thing this dialog exists to make
 * impossible to miss: another project can be quietly relying on THIS
 * project's cached narration/generated images (the global content-hash
 * cache, `backend/app/projects/deletion.py`'s own module docstring) with
 * no row of its own to show for it - deleting silently breaks that other
 * project's next render. See that module's docstring for exactly what the
 * cross-project check can and cannot catch.
 */
export function DeleteProjectDialog({
  projectId,
  projectName,
  open,
  onOpenChange,
}: {
  projectId: string
  projectName: string
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const preview = useDeletionPreview(projectId, { enabled: open })
  const deleteMutation = useDeleteProject()

  function handleClose(next: boolean) {
    onOpenChange(next)
    if (!next) deleteMutation.reset()
  }

  const data = preview.data
  const totalRows = data ? Object.values(data.row_counts).reduce((a, b) => a + b, 0) : null
  const dependencies = data
    ? [...data.narration_dependencies, ...data.generated_clip_dependencies]
    : []
  // Names, not just ids - a human deciding whether to proceed reads names,
  // not UUIDs. Deduplicated because one other project routinely shares
  // several cache entries (dense sharing is the whole reason this dialog
  // exists - see the module docstring above).
  const affectedNames = [...new Set(dependencies.map((d) => d.depended_on_by_project_name))]

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Delete "{projectName}"?</DialogTitle>
          <DialogDescription>
            Permanently removes this project's database rows and every file on disk. There is no
            undo.
          </DialogDescription>
        </DialogHeader>

        {preview.isLoading && (
          <div className="space-y-2">
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-2/3" />
          </div>
        )}

        {preview.isError && (
          <ErrorNotice
            message={
              preview.error instanceof Error
                ? preview.error.message
                : 'Could not check what this would delete.'
            }
          />
        )}

        {data && (
          <div className="space-y-3 text-sm">
            <p className="text-muted-foreground">
              {totalRows} database row{totalRows === 1 ? '' : 's'} across this project's tables,
              plus{' '}
              {data.storage_exists
                ? `${formatBytes(data.storage_bytes)} of files on disk`
                : 'no files on disk (its storage directory is already absent)'}
              .
            </p>

            {dependencies.length > 0 && (
              <Alert variant="warning">
                <AlertTriangle className="h-4 w-4" />
                <AlertTitle>
                  {affectedNames.length} other project{affectedNames.length === 1 ? '' : 's'} reuse
                  {affectedNames.length === 1 ? 's' : ''} cached narration or images from this one
                </AlertTitle>
                <AlertDescription className="space-y-1">
                  <p>
                    {affectedNames.join(', ')} {affectedNames.length === 1 ? 'has' : 'have'} never
                    generated {dependencies.length === 1 ? 'this narration line or image' : 'these narration lines or images'}{' '}
                    itself - it's been reusing this project's copy. Deleting this project deletes
                    that copy, so the next time {affectedNames.length === 1 ? 'it renders' : 'they render'},{' '}
                    {dependencies.length === 1 ? 'it' : 'each one'} will have to regenerate{' '}
                    {dependencies.length === 1 ? 'it' : 'them'} from scratch (est.{' '}
                    {formatCostCents(data.total_respend_estimate_cents)}).
                  </p>
                </AlertDescription>
              </Alert>
            )}

            {deleteMutation.isError && (
              <ErrorNotice
                message={
                  deleteMutation.error instanceof Error
                    ? deleteMutation.error.message
                    : 'Delete failed.'
                }
              />
            )}
          </div>
        )}

        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => handleClose(false)}
            disabled={deleteMutation.isPending}
          >
            Cancel
          </Button>
          <Button
            variant="destructive"
            disabled={!data || deleteMutation.isPending}
            onClick={() =>
              deleteMutation.mutate(projectId, {
                onSuccess: () => handleClose(false),
              })
            }
          >
            {deleteMutation.isPending ? 'Deleting…' : 'Delete permanently'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
