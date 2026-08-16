import type { AssetSource } from '@/lib/types'
import { ASSET_SOURCE_BADGE_CLASS, ASSET_SOURCE_LABEL } from '@/lib/asset-source'
import { cn } from '@/lib/utils'

export function AssetSourceBadge({ source }: { source: AssetSource }) {
  return (
    <span
      className={cn(
        'inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium',
        ASSET_SOURCE_BADGE_CLASS[source],
      )}
    >
      {ASSET_SOURCE_LABEL[source]}
    </span>
  )
}
