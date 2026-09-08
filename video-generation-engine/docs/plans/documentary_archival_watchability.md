# Documentary Archival — Watchability Pass

**Status:** PLAN. Nothing built yet.
**Written 2026-09-08**, off the back of a full measurement pass over
project `3ad7d0ca` ("plato uncovered", 29 scenes, 86 shots, 6:24, Hindi)
and one blunt piece of user feedback: *"the video is boring to be
honest."*

**Scope: the `documentary_archival` style ONLY.** That style band is
also the scope mechanism — it is the 16:9 long-form default, so
directing it directs long-form without touching `retention_fast`,
`archival_montage`, `illustrated_risograph` or `stillness`. Every task
below either edits that band's own row in `STYLE_PACING_BANDS` or adds a
style-scoped prompt fragment that only this style loads. No task changes
a shared default.

---

## Verdict up front

The render pipeline is not the problem. The film is technically
well-formed and creatively inert, and two measurements explain almost
all of it:

- **84 of 86 shots are still photographs.** Only 2 shots are generated
  clips. 98% of the runtime is a photo with a drift over it.
- **100% of the runtime has someone talking.** Narration totals 384.56s
  against a 384.53s video. There is not one second of silence in 6
  minutes 24 seconds.

A slideshow that never stops talking. That is a format problem, and it
sits upstream of every knob in the renderer.

`long_form_direction.md`'s verdict ("long-form has a look system and no
direction system") has been PARTLY addressed since it was written -
correcting an error in the first draft of this document, which claimed
`shot_planner_styles/` held only `archival_montage.md`. It holds five
fragments, `documentary_archival.md` among them, and that fragment is
substantive: it fixes the camera register (no whip pans, `intensity`
held inside 0.10-0.25), bans `punch_in` outright once a film has acts,
asks for movement variety across an act, and owns chapter cards and
`fadeblack` as the act-boundary transition.

So the CREATIVE direction exists. What is still absent is the NUMERIC
direction: this style's band row carries `target_shot_duration_s=None`,
`max_shots_override=None`, `min_shot_duration_s_override=None`,
`max_shot_duration_s_override=None`. Nothing bounds a shot's length.
That is what produced a 4.67s median, three shots over 8s, and 17% of
the film frozen - the fragment tells the planner how to move the camera,
and nothing tells it how long to hold.

**Consequence for W9 below: it is a REVISION of an existing fragment,
not a new file. And one recommendation in this plan (raising camera
intensity) directly contradicts that fragment's explicit instruction -
see W9's own warning.**

---

## Measurements (2026-09-08, project 3ad7d0ca — do not re-derive)

Pacing and motion:

| metric | measured |
|---|---|
| shots / scenes / acts | 86 / 29 / 5 |
| shot duration | min 1.45, p25 3.70, **median 4.67**, p75 5.74, p90 6.93, max 10.40 |
| shots over 8s | 3 (one at 10.40s) |
| fully static shots (`movement: static`) | **13 = 69.8s = 17% of the film** |
| longest static holds | 7.83s, 7.76s, 7.48s |
| camera intensity range | 0.12–0.20 (a 12–20% drift over ~5s) |
| transitions | 37% `cut`, **53% `dissolve`** (0.4–0.8s), 6% `fadeblack`, 3% `fade` |
| framing mix | close 38%, medium 34%, wide 24%, split 3% |
| shots using `layers` (parallax) | **0** |
| shots using `reveal_direction` | **0** |
| `text_card` | **5 of 86** (one per act) |
| `sfx_cue` | **8 of 86 (9%)**, every cue worded "faint …" |

Audio and structure:

| metric | measured |
|---|---|
| narration coverage | **100.0%** of runtime |
| narration pace | 11.1 chars/s overall |
| audio loudness | −15.9 LUFS integrated, **LRA 3.2 LU** |
| act durations | 69.2 / 83.1 / 81.4 / 75.6 / 108.2s (flat, no escalation) |
| first 30s | 6 shots, incl. an **8.21s shot starting at 9.8s** |
| repeated media | 16 of 86 bindings reuse 8 assets — spacing is GOOD (the 5× asset lands at 6/108/202/298/400s) |

Things measured and found **healthy** — do not "fix" these: asset repeat
spacing, framing variety, narration pace, caption styling (karaoke word
highlight, 897 cues, Noto Sans Devanagari 58px / 8px outline).

---

## The architectural blocker: silence is currently inexpressible

This is the finding with real weight, and it is not a prompt problem.

`narration_fit` derives every shot's duration **from its own spoken
characters**. `Shot.narration_span` is mandatory, shots must tile their
scene's `narration_text` with no gap, and
`_spoken_durations_for_scene` explicitly rejects a span covering only
whitespace ("nothing is actually spoken, so it cannot be timed against
narration").

So a deliberate silent beat — image lands, bed swells, nobody talks for
a second and a half — **has nowhere to live in the data model.** Every
shot must contain words. That single constraint is why the film feels
relentless, and no amount of style-prompt tuning can produce a pause.

Consequence for this plan: silence is **W9**, deliberately last, gated,
and explicitly NOT part of tonight's work. See its section.

---

## Cost warning, read before starting

Tightening shot durations against a **fixed** narration length means
MORE shots. At the measured 384s of narration:

- median 4.67s → 86 shots (today)
- target ~3.0s → **roughly 120–130 shots**

Every new shot needs a picture. That is a real asset-generation spend
per re-plan, and it recurs on every re-plan while tuning. The whole
project has spent 150¢ to date, so this is not ruinous, but it is not
free either, and iterating on W1/W2 means paying it repeatedly.

**Therefore the tiers are ordered so the free work lands first.** Tier A
changes no planning and needs no new assets. Tier B re-plans and buys
pictures.

---

## Tier A — no re-plan, no new assets, ships tonight

Independent of the planner. None of these change shot counts, so none
of them spend money on images. All are verifiable by probing the
re-rendered file the way tonight's diagnosis was done.

### W1 — Colour tagging and range normalisation
**Where:** `renderer/slideshow.py::_h264_bitexact_args`, plus the
source→frame scale step.
**Problem, measured:** the delivered file is `pix_fmt=yuvj420p`,
`color_range=pc`, with `color_space`, `color_primaries` and
`color_transfer` all `unknown`. Luma genuinely spans **YMIN=0 /
YMAX=255**, so this is real full-range data, not a mislabel. Sources
disagree with each other: a `.jpg` decodes 0–255 (`pc`, `bt470bg`), a
`.webp` decodes 2–230 (`tv`), PNGs arrive `rgba`/`gbr`.
`grep` for `-color_range|-colorspace|-color_primaries|-color_trc|in_range|out_range`
across `backend/app` returns **nothing** — there is no colour
management anywhere.
**Note the trap:** `yuvj420p` is not a different layout from
`yuv420p`; the `j` is the range flag surfacing. `render_pixel_format
= "yuv420p"` was honoured and is not the bug. Fixing `pix_fmt` will
keep missing.
**Do:** normalise range and matrix at ingest (`scale` with explicit
`in_range`/`out_range`), and tag the encode BT.709 limited.
**Risk:** changes output bytes → changes the render fingerprint →
one-time full re-render of all 40 projects. That is the I5 determinism
guarantee working, not a fault.
**Verify:** `ffprobe` shows `yuv420p`/`tv`/`bt709`; `signalstats` YMIN
≥ 16 and YMAX ≤ 235.

### W2 — Loudness to −14 LUFS
Measured −15.9. YouTube normalises to about −14 and only ever turns
audio **down**, so this plays permanently quieter than competing
videos. A loudness stage already exists (`pre_loudness_final.mp4`).

### W3 — Stereo audio at a real bitrate
Measured **mono, 69.9 kbps**. The music bed is collapsed to mono. Go
stereo at 128–192 kbps.

### W4 — Caption safe area
`MarginV 29` of `PlayResY 720` puts captions **4.0%** from the frame
bottom. YouTube's progress bar and controls occupy roughly the bottom
8–10%, so the last line is occluded whenever the player UI is up. Move
to ~10%.

### W5 — Subtitle sidecar (`.srt`/`.vtt`)
`renders/` contains exactly one file: `final.mp4`. Captions are burned
in only — no selectable CC, no auto-translation, no indexable caption
text. **Highest value per unit of effort on this list:** the pipeline
already stores character-level alignment for all 29 scenes, so this is
a formatting pass over data already paid for.

### W6 — Chapter timestamps
5 clean act boundaries already exist at **0 / 69 / 152 / 234 / 309s**,
with act titles already written ("The Myth and the Burned Scroll",
"The Philosopher King Experiment", …). Emit them as a description
string. Note: `chapter` in `planners/shot/planner.py` refers to
act-boundary text cards, not YouTube chapters — different thing, no
existing machinery to reuse.

### W7 — The 6.47s audio overrun
Known from earlier tonight and still open. `mux_music`'s
`amix duration=longest` turns two 384.56s inputs into 390.92s;
`shortest` and `first` both yield 384.56. The trailing 6.47s is audible
(mean −28.9 dB, max −13.9 dB vs the film body's −16.5/−0.3). **Do not
just flip the flag** — `mux_music`'s docstring records that `first` was
tried and rejected because it can truncate the mix. Needs real thought.

---

## Tier B — re-plans and buys pictures

### W8 — Give the band actual pacing direction
**Where:** `script/styles.py`, the `documentary_archival` row only.
All four duration knobs are `None` today. Proposed starting values, to
be tuned by ear against one re-plan:

| knob | today | proposed | why |
|---|---|---|---|
| `target_shot_duration_s` | `None` | ~3.0–3.5 | measured median is 4.67; stills need faster cuts than motion because there is no intrinsic movement to hold the eye |
| `max_shot_duration_s_override` | `None` | ~5.0 | kills the 8s+ holds directly; 3 shots exceed 8s today |
| `min_shot_duration_s_override` | `None` | ~2.0 | floor, so it tightens without becoming a reel |
| `music_bed_gain_db` / `music_duck_gain_db` | `None` | tune | LRA 3.2 LU is almost no dynamic range |

`max_shot_duration_s_override` alone reclaims most of the 69.8s of
frozen screen time and is the single highest-impact number here.

### W9 — REVISE `shot_planner_styles/documentary_archival.md`
The file EXISTS (9 lines) and already owns camera register, act-aware
shot grammar, movement variety, chapter cards and `fadeblack`. This is
an edit, not a new file. What it does not yet address:

- **Transitions.** `cut` as the default; `dissolve` reserved for a real
  change of era, place or mood. Today it is 53% dissolve — museum-kiosk
  grammar, and the fragment currently says nothing about transition MIX.
  Note `transition_sfx_structural_only=True` on this band exists
  *because* long-form dissolves heavily (A15); revisit that flag once
  the dissolve rate drops.
- **Holding time.** The fragment tells the planner how to MOVE and
  nothing about how long to HOLD. 17% of the film is frozen and three
  shots exceed 8s. This is mostly W8's job (band numbers), but the
  fragment should stop asking for "the coarser end of fragment
  granularity" without an upper bound.

> ⚠ **Camera intensity: do NOT push it.** An earlier draft of this plan
> recommended raising intensity from 0.12-0.20 to 0.3+. The fragment
> explicitly instructs the opposite - `intensity` stays inside
> 0.10-0.25, "do not push higher even on an `emphasize` beat; a
> documentary earns its emphasis from what the shot shows, not from a
> harder push." That is a deliberate, written creative decision and this
> plan defers to it. If the film still feels inert after W8, the honest
> lever is shot LENGTH and cut rhythm, not move size. Revisit the
> intensity band only as an explicit, ear-signed reversal of that line.
- **Parallax / `layers`.** Zero shots use it despite being built. Depth
  on a still is the cheapest production value available. Note
  `CameraMovement.PARALLAX` with empty `layers` is a documented
  unguarded no-op — direct both together or neither.
- **`reveal_direction`.** Also zero. Same argument.
- **Text cards.** 5 of 86 today. Copy `archival_montage.md`'s per-scene
  framing verbatim in spirit — it correctly warns the planner it sees
  one scene and cannot reason about a project-wide rate.
- **SFX cues.** 9% of shots, every one worded "faint". Ask for cues
  with presence on impact beats.

**Watch out:** adding this file flips
`suppress_camera_language=style_fragment is not None` to True, so the
Director's `camera_language` stops reaching the shot planner for this
style (Q6 — the two contradict with no stated precedence). That is
intended, but it means the fragment must now own camera direction
completely. Do not add a half-written fragment.

### W10 — Hook discipline
First 30s is 6 shots including an 8.21s shot at 9.8s. Whether this is
best expressed as a band knob or a fragment instruction is open; W8's
`max_shot_duration_s_override` may cover it incidentally. Measure after
W8 before adding anything bespoke.

### W11 — 1080p canvas
`render_width=1280 / render_height=720` on this band. Source art
supports more: 15 assets at 2688×1536 or 2752×1536, 3 at 5184×3456 or
larger. **But** 24 assets sit at 1376×768 or 1280×720, and 85% of shots
carry Ken Burns motion that crops *into* the frame — so those would go
soft at 1080p. Real win for about half the film, not free. Do W1 first;
correct colour on 720p beats wrong colour on 1080p.

---

## W12 — Silence (GATED, not tonight)

See "architectural blocker" above. A silent beat requires a shot with
no `narration_span`, timed independently of the master clock, that
`narration_fit` tolerates and the audio mux pads with real silence.

That touches the D1 master-clock and D5 duration guarantees, which are
the two things in this system most carefully proven and most load-
bearing. `narration_fit.py`'s module docstring explains why its
arithmetic telescopes exactly to the scene's real narrated duration —
introducing untimed shots breaks that property by construction, so the
design has to say what replaces it.

**Gate:** do not start until Tier A has shipped and W8/W9 have been
tuned through at least one re-plan. It is plausible that faster cutting,
real camera motion and dynamic audio recover enough energy that silence
becomes a refinement rather than a rescue. Decide with a watched cut in
hand, not from this document.

---

## Recommended order for tonight

1. **W1** (colour) — real defect, verifiable, no re-plan
2. **W5** (SRT) — cheapest genuine capability gain
3. **W2 + W3 + W4** (loudness, stereo, caption margin) — small, independent
4. **W6** (chapters) — trivial once W5's alignment walk exists
5. **W8** (band numbers) — first thing that needs a re-plan; costs pictures
6. **W9** (style fragment) — the big creative lever; tune alongside W8

W7 and W11 next session. W12 gated.

---

## Verification

Tonight's diagnosis established the method; reuse it rather than
trusting status fields:

- `ffprobe` for `pix_fmt` / `color_range` / `color_space`, and
  `signalstats` for actual YMIN/YMAX — a status of "completed" told us
  nothing about the 6.47s overrun or the colour range.
- `ebur128` for integrated LUFS and LRA.
- Re-run the timeline measurement script against the new version and
  diff the table in "Measurements" above. Median shot duration, static
  percentage, dissolve share, `layers`/`reveal` counts and text-card
  count are the five numbers that say whether W8/W9 actually landed.
- Watch it. Every number above can improve while the film stays boring;
  the numbers are evidence, not the goal.
