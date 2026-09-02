import { useState } from 'react'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Label } from '@/components/ui/label'
import { Button } from '@/components/ui/button'
import { ResolutionWarningBadge } from '@/components/ResolutionWarning'
import { computeResolutionWarning, readMediaDimensions, type ResolutionWarning } from '@/lib/resolution'
import type { Camera } from '@/lib/types'

/** Shared by Gate 1 (override/insert a missing or found image) and Gate 2
 * ("replace" a generated image) — both end up calling the same
 * `POST /shots/{shot_id}/override` endpoint (A9/A10/A24), just from a
 * different starting state. */
export function OverrideDialog({
  open,
  onOpenChange,
  title,
  description,
  camera,
  onSubmit,
  isPending,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  description: string
  camera: Camera | undefined
  onSubmit: (file: File, description: string) => void
  isPending: boolean
}) {
  const [file, setFile] = useState<File | null>(null)
  const [fileDescription, setFileDescription] = useState('')
  const [warning, setWarning] = useState<ResolutionWarning | null>(null)

  async function handleFile(f: File | null) {
    setFile(f)
    if (!f) {
      setWarning(null)
      return
    }
    try {
      const { width, height } = await readMediaDimensions(f)
      setWarning(computeResolutionWarning(width, height, camera))
    } catch {
      setWarning(null)
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        onOpenChange(o)
        if (!o) {
          setFile(null)
          setFileDescription('')
          setWarning(null)
        }
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <div>
            <Label htmlFor="override-file" className="mb-2 block">
              Image or video
            </Label>
            <Input
              id="override-file"
              type="file"
              accept="image/*,video/mp4,video/quicktime,video/webm"
              onChange={(e) => void handleFile(e.target.files?.[0] ?? null)}
            />
          </div>
          {warning && <ResolutionWarningBadge warning={warning} />}
          <div>
            <Label htmlFor="override-description" className="mb-2 block">
              Description (optional)
            </Label>
            <Textarea
              id="override-description"
              value={fileDescription}
              onChange={(e) => setFileDescription(e.target.value)}
              placeholder="What this image or clip shows"
              className="min-h-[60px]"
            />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button disabled={!file || isPending} onClick={() => file && onSubmit(file, fileDescription)}>
            {isPending ? 'Uploading…' : 'Use this image'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
