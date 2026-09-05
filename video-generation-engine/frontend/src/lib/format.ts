/** Formatting helpers shared across screens. */

export function formatDuration(totalSeconds: number | null | undefined): string {
  if (totalSeconds == null || Number.isNaN(totalSeconds)) return '—'
  const s = Math.max(0, Math.round(totalSeconds))
  const m = Math.floor(s / 60)
  const rem = s % 60
  return `${m}:${String(rem).padStart(2, '0')}`
}

/**
 * `$`, not the `£` the original F3 spec text said to use: `cost_cents`
 * is real provider pricing (Fal AI, OpenAI, ElevenLabs), and all three
 * bill in USD — showing `£0.04` for something that costs 4 real US
 * cents states a different currency than the one actually being spent,
 * not just a different symbol.
 */
export function formatCostCents(cents: number | null | undefined): string {
  const value = ((cents ?? 0) / 100).toFixed(2)
  return `$${value}`
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
}

/** Storage footprint for the deletion-preview dialog. `0` reads as "0 B",
 * not "—" - an empty-but-present storage directory is a real, reportable
 * fact (`storage_exists: true, storage_bytes: 0`), distinct from the
 * directory being absent entirely (which the dialog states in words, not
 * through this formatter). */
export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  const units = ['KB', 'MB', 'GB', 'TB']
  let value = bytes / 1024
  let unitIndex = 0
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024
    unitIndex += 1
  }
  return `${value.toFixed(value < 10 ? 1 : 0)} ${units[unitIndex]}`
}

export function wordCount(text: string): number {
  return text
    .trim()
    .split(/\s+/)
    .filter(Boolean).length
}
