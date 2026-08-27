import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'

/**
 * ui_style_feature_coverage.md §4/§2.2: the style/frame-aspect/language
 * pickers in NewProject.tsx each hand-rolled this exact button+`cn()`
 * pattern independently — three copies of one pattern, no shared
 * component. Extracted here so a 4th style (or any future option list)
 * doesn't become a 4th copy. `preview` is unused today but built in from
 * the start (ui_style_feature_coverage.md §5) so style previews slot in
 * without a second migration. Used by the style picker as of P-UI5.
 */
export function OptionCard({
  selected,
  onSelect,
  label,
  hint,
  preview,
  disabled = false,
}: {
  selected: boolean
  onSelect: () => void
  label: string
  hint?: string
  preview?: ReactNode
  disabled?: boolean
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      disabled={disabled}
      className={cn(
        'rounded-md border px-3 py-2.5 text-left transition-colors',
        selected
          ? 'border-primary bg-primary/10'
          : 'border-border hover:border-primary/40 hover:bg-accent/40',
        disabled && 'cursor-not-allowed opacity-50 hover:border-border hover:bg-transparent',
      )}
      aria-pressed={selected}
    >
      {preview && (
        <div className="-mx-3 -mt-2.5 mb-2 overflow-hidden rounded-t-[5px]">
          {preview}
        </div>
      )}
      <div className="text-sm font-medium">{label}</div>
      {hint && <div className="mt-0.5 text-xs text-muted-foreground">{hint}</div>}
    </button>
  )
}
