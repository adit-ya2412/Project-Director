## Style override: retention_fast

This project uses the `retention_fast` style - rapid cuts, punch-in zoom snaps, driving pace. The following overrides the base instructions above where they conflict; everything else (one idea per shot, intent, historical grounding of the `prompt` field) still applies.

- **Prefer the finest possible fragment granularity.** Give each shot the smallest contiguous fragment range that still makes sense as one idea - one fragment per shot wherever that fragment is coherent on its own, rather than combining several fragments into a longer shot. You will be given a lower minimum shot duration than usual for this reason - use the room it gives you.
- **Camera: prefer `punch_in` for most shots.** This style's motion is a hard, stepped zoom-in snap, not the slow drift described in the base camera table above. Reserve `static` only for a shot that genuinely needs to hold still (a moment the narration lingers on), and treat the base table's `slow_push`/`slow_zoom`/`pan`/`pull_back` guidance as belonging to a different, slower style, not this one.
- **Transitions: `cut` only, never `dissolve` or `fade`.** This overrides the base prompt's dissolve-for-continuity guidance entirely - a fast, driving style reads as continuous through pace and rhythm, not through crossfades, and a dissolve between very short shots reads as sluggish rather than connective.
- **Respect the shot-count and duration limits you are given exactly** - they are tuned specifically for this style's faster pace, not the general-purpose defaults.
