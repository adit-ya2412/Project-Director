import type { ProjectStatus } from '@/lib/types'
import { Badge } from '@/components/ui/badge'
import { AlertCircle, CheckCircle2, Clock, Film, Eye, PenLine } from 'lucide-react'

const STATUS_META: Record<
  ProjectStatus,
  { label: string; variant: 'default' | 'secondary' | 'destructive' | 'success' | 'warning' | 'outline'; icon: typeof Clock }
> = {
  created: { label: 'Created', variant: 'outline', icon: PenLine },
  script_uploaded: { label: 'Script uploaded', variant: 'secondary', icon: PenLine },
  awaiting_approval: { label: 'Needs your review', variant: 'warning', icon: Eye },
  awaiting_review: { label: 'Needs your review', variant: 'warning', icon: Eye },
  rendering: { label: 'Rendering', variant: 'secondary', icon: Clock },
  completed: { label: 'Completed', variant: 'success', icon: CheckCircle2 },
  failed: { label: 'Failed', variant: 'destructive', icon: AlertCircle },
}

export function StatusChip({ status, className }: { status: ProjectStatus; className?: string }) {
  const meta = STATUS_META[status] ?? { label: status, variant: 'outline' as const, icon: Film }
  const Icon = meta.icon
  return (
    <Badge variant={meta.variant} className={className}>
      <Icon className="mr-1 h-3 w-3" />
      {meta.label}
    </Badge>
  )
}
