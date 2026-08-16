import { AlertTriangle, CheckCircle2 } from 'lucide-react'
import type { ResolutionWarning } from '@/lib/resolution'
import { cn } from '@/lib/utils'

const VERDICT_CLASS: Record<ResolutionWarning['verdict'], string> = {
  fine: 'bg-success/15 text-success border-success/30',
  soft: 'bg-warning/15 text-warning border-warning/30',
  bad: 'bg-destructive/15 text-destructive border-destructive/30',
}

/**
 * F7: "warn, never block" — always informational, never disables anything
 * downstream. Shows the real numbers, per the spec's own example format
 * ("480×640 → upscaled 1.7×, may look soft").
 */
export function ResolutionWarningBadge({ warning }: { warning: ResolutionWarning }) {
  if (warning.verdict === 'fine') {
    return (
      <div className={cn('flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs', VERDICT_CLASS.fine)}>
        <CheckCircle2 className="h-3.5 w-3.5 shrink-0" />
        <span>{warning.message}</span>
      </div>
    )
  }
  return (
    <div className={cn('flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs', VERDICT_CLASS[warning.verdict])}>
      <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
      <span>{warning.message}</span>
    </div>
  )
}
