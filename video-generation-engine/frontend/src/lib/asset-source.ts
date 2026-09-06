/**
 * "Which shots are AI-generated is the thing the user reacts to most"
 * (F4/F6). Derived from `asset.provider` / presence of a generated clip —
 * NOT from `rung`, which only says which ladder position resolved a shot,
 * not which real provider served it (`historical_search` and
 * `public_domain` both can be served by either plain Wikimedia Commons
 * search or the entity-specific Wikipedia lookup — see resolve_assets.py).
 */
import type { AssetSource, ShotAssetDetail, ShotClipDetail, ShotProgress } from './types'

/** The classification rule itself, independent of which panel it's
 * fed — P3a needs the exact same rule for a split_frame shot's bottom
 * panel (`shot.secondary.asset`/`.clip`), and a second copy of this
 * switch would be exactly the kind of drift R1 warns about. */
export function assetSourceFromDetail(
  asset: ShotAssetDetail | null,
  clip: ShotClipDetail | null,
): AssetSource {
  if (clip) return 'generated'
  if (asset) {
    switch (asset.provider) {
      case 'project_assets':
        return 'uploaded'
      case 'wikipedia_entity':
        return 'entity'
      case 'wikimedia':
      case 'pexels':
        return 'archival'
      default:
        return 'unknown'
    }
  }
  return 'unknown'
}

export function shotAssetSource(shot: ShotProgress): AssetSource {
  return assetSourceFromDetail(shot.asset, shot.clip)
}

export const ASSET_SOURCE_LABEL: Record<AssetSource, string> = {
  archival: 'Archival',
  entity: 'Wikipedia entity',
  generated: 'AI-generated',
  uploaded: 'Your upload',
  unknown: 'Unknown',
}

/** Tailwind classes per source — kept in one place so every screen agrees
 * on what "generated" looks like at a glance. */
export const ASSET_SOURCE_BADGE_CLASS: Record<AssetSource, string> = {
  archival: 'bg-blue-500/15 text-blue-300 border-blue-500/30',
  entity: 'bg-teal-500/15 text-teal-300 border-teal-500/30',
  generated: 'bg-purple-500/15 text-purple-300 border-purple-500/30',
  uploaded: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30',
  unknown: 'bg-secondary text-muted-foreground border-border',
}
