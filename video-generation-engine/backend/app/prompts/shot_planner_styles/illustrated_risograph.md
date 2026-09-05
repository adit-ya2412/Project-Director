## Style override: illustrated_risograph

This project uses the `illustrated_risograph` style - every picture in the film is a generated flat editorial illustration, in one locked world, with every human figure deliberately faceless. This is a FORMAT, not a documentary look: nothing in this scene is photographed, archival, or footage, and `prompt` must never say so. The following overrides the base instructions above where they conflict; everything else (one idea per shot, intent, fragment coverage) still applies.

- **`prompt` describes an illustration, never a photograph.** Drop the base prompt's "documentary photograph" framing entirely for this style. Every shot's `prompt` must, in substance, carry this exact world - restate it every time rather than paraphrasing it shorter across shots, since the world holds together across many shots because each one restates it, not because the model remembers the last one:

  > Bold risograph print illustration: only three spot colours - deep teal, fluorescent orange and black - carrying the coarse tooth and grain of off-white uncoated paper through the whole image as its surface. Heavy visible ink grain, coarse halftone dot texture, deliberate slight misregistration where colours overlap, high contrast, simplified graphic shapes. Bold, graphic and urgent in feeling. The image fills the frame completely, edge to edge.

  <!-- Do not add any noun naming a physical printed object to the token above.
  The measured reason, and the two separate incidents behind this rule, are in
  docs/plans/illustrated_faceless.md §1.7. That rationale is deliberately kept
  OUT of this file: `load_style_fragment` appends this ENTIRE file to the Shot
  Planner's system prompt, HTML comments included and not stripped, so every
  artefact noun spelled out here would be fed to the image model on every
  scene call - which is the exact thing §1.7 exists to prevent. Explain it in
  the plan; name nothing here. -->

- **Every human figure is faceless, and you must say so as a POSITIVE framing, never as a negation.** Face-biased image models honour a negation unreliably; all four framings below were measured to work and every one of them states what the picture DOES show. Use one per shot, and vary which one across the scene so it never reads as one repeated trick:
  - seen from behind
  - a solid silhouette against strong backlight
  - a blank, featureless face (no eyes, nose, or mouth)
  - cropped above the chin

- **State the figure's skin tone/ethnicity and hair colour explicitly, in every shot that shows one.** Never leave either to the model's default - skin tone was measured drifting lighter the more abstract the treatment got, and an unstated hair colour came back ginger (the palette's amber bled into it). Ground both in this scene's historical_period/visual_style or the Director's creative context, exactly as the base prompt's historical-grounding principle already asks - do not invent an ethnicity the story never established.

- **If the Director's creative context (`visual_style`) carries a figure block for a recurring character, and this shot shows that character, reproduce that figure block in `prompt` essentially verbatim.** This is the same "restate it every time rather than paraphrasing" reasoning the world token above uses, and for the same reason: you are called once per scene, cannot see any other scene, and have no memory of how a previous shot rendered this figure. Measured missing in a real render (project 7df10f6c-e6b9-4275-b88a-7f07d0178011): the same named character came back as a different person - different build, hair, and wardrobe - at different points in the film, because each scene's Shot Planner call invented its own figure instead of reusing the one already given. Do not paraphrase the figure block into a shorter description or invent a different build/hairstyle/wardrobe for the same named character.

- **Say "plain flat background" on any shot showing a chart, bars, a diagram, or another graphic** - the graphic sits on an empty, uniform field with generous margins and nothing else in the frame. Use that exact phrasing; other wordings for the same idea were measured to fail in a specific and instructive way, recorded in `illustrated_faceless.md` §1.3, and named nowhere in this file for the reason the comment above the world token gives.

- **Framing depends on this project's canvas** (the `- canvas: WxH (...)` line under "Long-form context" above; this style always supplies one, since its canvas is fixed at planning start). On a portrait canvas (`9:16`), this is the tighter edit: keep the frame close, let one figure or one graphic dominate it, and avoid crowding several elements into a single shot. On a landscape canvas (`16:9`), this is the wider edit: room to establish an environment before framing the figure is welcome, and more than one graphic element can share a frame when the composition genuinely supports it. The two are planned as separate projects, never one reframed into the other - do not try to satisfy both directions in a single shot.

- **No `split_frame` in this style.** A comparison beat is two consecutive single-frame shots instead of one split shot - this format has not yet built two independently generated, world-consistent panels sharing a single comparison frame. Treat a `compare`-intent shot the same as any other intent for camera purposes.

- **A `parallax` shot needs exactly two `layers`, in order: `background` then `subject`.** Choose `camera.movement: parallax` only for a shot where the figure genuinely reads as separate from its setting - reserve it, do not reach for it on every shot. When you do, give `layers` exactly two entries:
  - The first, `role: background`, describes the full setting exactly the way this style's `prompt` always would - restate the world token in full, same as every other shot.
  - The second, `role: subject`, describes only the figure or focal element, isolated on one perfectly even, solid magenta field that fills the frame completely, edge to edge - flat, shadowless lighting, and the figure as the sole content in the frame.

  `prompt` still follows every instruction above regardless of `camera.movement`. Every shot that is NOT `parallax` leaves `layers` empty.
