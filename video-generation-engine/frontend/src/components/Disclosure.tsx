import type { ReactNode } from 'react'
import { ChevronRight } from 'lucide-react'

/** A native <details> disclosure for "technical detail behind a
 * disclosure" (F3) — no JS state needed, and it's free accessibility. */
export function Disclosure({ summary, children }: { summary: string; children: ReactNode }) {
  return (
    <details className="group mt-1">
      <summary className="flex cursor-pointer list-none items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
        <ChevronRight className="h-3 w-3 transition-transform group-open:rotate-90" />
        {summary}
      </summary>
      <div className="mt-1.5 rounded-md bg-black/30 p-2 font-mono text-xs text-muted-foreground">
        {children}
      </div>
    </details>
  )
}
