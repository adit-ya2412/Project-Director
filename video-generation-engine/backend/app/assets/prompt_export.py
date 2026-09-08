"""P0 (docs/plans/gate_panel_overrides.md, §3/§7): bulk-export every image
prompt a project's active timeline will ever ask a provider for.

The measured problem (§1): the user's real cost-saving workflow is to copy
a shot's prompt off the approval gate, generate it for free in a provider
whose quota they already pay for (Grok), and upload the result instead of
paying fal.ai 4c/image. That works one shot at a time. On a 41-shot film
it is 61 images to copy one at a time, and the 20 parallax layer prompts
(`ShotLayer.prompt`, styled via `layer_styled_prompt`) are never shown in
the gate UI at all - this module is the "give them every prompt in one
action" answer.

**R1: every prompt below is built by calling the SAME functions the real
generation path calls, never a re-derivation.** `styled_prompt` (renamed
from `_styled_prompt` for this - see its own docstring for why a rename
rather than an import of a private name, or a second copy) is what
`generate_image_real` feeds `_generate_image_once` as `base_prompt`, sent
completely unmodified from there - so this module's primary-image prompt
is byte-identical to what a real generation call would send. Layers are
`layer_styled_prompt`, already public for the identical reason
(`render.py`'s own render-time lookup needs it too).

Deliberately plain text, not JSON (§3 P0: "not JSON unless the user
asks") - the destination is a paste box in someone else's chat UI, never
code that would parse a schema.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.schemas.timeline import CameraMovement, Timeline
from app.script.styles import resolve_generation_request_format, resolve_render_format
from app.workflow.steps.resolve_assets import layer_styled_prompt, styled_prompt


@dataclass(frozen=True)
class PromptExportEntry:
    """One image this project will ask a provider for.

    `image_label` is a short, stable, machine-sortable id for which image
    on the shot this is (`"primary"`, `"layer_0"`, `"layer_1"`, ...) -
    `role` names a layer's depth role (`LayerRole.value`, e.g.
    `"background"`/`"subject"`) for a layer, `None` for a primary, which
    has no role of its own.

    `is_parallax_fallback` is true exactly when this is the PRIMARY image
    of a `camera.movement == PARALLAX` shot - see `build_prompt_export_
    entries`'s own docstring for what that means and why it matters
    enough to flag rather than just export."""

    scene_id: str
    shot_id: str
    image_label: str
    role: str | None
    is_parallax_fallback: bool
    prompt: str


def build_prompt_export_entries(timeline: Timeline) -> list[PromptExportEntry]:
    """Scene-then-shot order - the same walk `Timeline.all_shots` does
    internally, kept here (rather than calling that method) only because
    each entry also needs its OWN scene id, which `all_shots` discards.

    One `RenderFormat` resolved ONCE for the whole project
    (`timeline.metadata.render_style`/`frame_aspect` are project-wide
    settings, not per-shot) and threaded into every prompt call below -
    mirrors `generate_image_real`'s own single `resolve_render_format`
    call per generation exactly; a per-shot resolve here would be wasted
    work at best and a drift risk at worst if a future style ever made
    the canvas conditional on something shot-level.

    **Why a `PARALLAX` shot's primary is flagged, not skipped or listed
    last.** It IS still generated in the real pipeline - `ResolveAssetsStep
    .run`'s `needs_layers` gate only ever ADDS layer generation for this
    movement, it never suppresses the shot's own primary (verified by
    reading that gate on 2026-09-08; the brief this module was built from
    asserted the same and this re-check found nothing different) - so a
    real render always has this image on file. But `render.py`'s own
    lookup (`shot_layer_images` + `should_composite_parallax`,
    `app/renderer/slideshow.py`) only ever reaches for the primary when a
    plane failed to resolve; when both planes resolve, the finished film
    never shows it. Generating this in Grok too would waste the exact
    effort this export exists to save, so it is labelled a fallback
    rather than presented as one of the shot's real pictures.

    Keyed on `camera.movement` alone, not on whether `shot.layers` is
    actually well-formed (two entries, background-then-subject -
    `should_composite_parallax`'s own structural check). A `PARALLAX`
    shot with fewer than two layers is already a documented, if useless,
    legal state (`CameraMovement.PARALLAX`'s own docstring - nothing
    today's planner writes produces it, but nothing rejects it either);
    this export states the structural fact "this movement has a fallback
    rule", true regardless of whether THIS shot's layers currently
    exercise it, rather than re-deriving `should_composite_parallax`'s
    full precondition (which also needs resolved clip paths that do not
    exist yet at export time, before anything has been generated)."""
    style = timeline.metadata.render_style
    frame_aspect = timeline.metadata.frame_aspect
    frame = resolve_render_format(style, frame_aspect=frame_aspect)
    creative_context = timeline.creative_context

    entries: list[PromptExportEntry] = []
    for scene in timeline.scenes:
        for shot in scene.shots:
            entries.append(
                PromptExportEntry(
                    scene_id=scene.id,
                    shot_id=shot.id,
                    image_label="primary",
                    role=None,
                    is_parallax_fallback=shot.camera.movement == CameraMovement.PARALLAX,
                    prompt=styled_prompt(shot, creative_context, frame=frame),
                )
            )
            for index, layer in enumerate(shot.layers):
                entries.append(
                    PromptExportEntry(
                        scene_id=scene.id,
                        shot_id=shot.id,
                        image_label=f"layer_{index}",
                        role=layer.role.value,
                        is_parallax_fallback=False,
                        prompt=layer_styled_prompt(shot, layer, creative_context, frame=frame),
                    )
                )
    return entries


def _entry_heading(entry: PromptExportEntry) -> str:
    if entry.image_label == "primary":
        if entry.is_parallax_fallback:
            return "PRIMARY — fallback only, used if a parallax plane fails to resolve"
        return "PRIMARY"
    index = entry.image_label.removeprefix("layer_")
    role = f" ({entry.role})" if entry.role else ""
    return f"LAYER {index}{role}"


def render_prompt_export_text(
    timeline: Timeline,
    entries: list[PromptExportEntry],
    *,
    project_name: str,
) -> str:
    """The plain-text blob the export endpoint hands back.

    **§7's least obvious requirement, and the reason this function exists
    separately from `build_prompt_export_entries` instead of formatting
    inline there:** the real pipeline sends size as an API parameter
    (`image_size: {width, height}`, from `resolve_generation_request_
    format`) that simply does not exist when a human pastes prompt text
    into a provider's chat UI. Measured 2026-09-06 against this exact 9:16
    film with no orientation words in the prompt at all: Grok returned
    784x1168 (2:3), Qwen returned 1664x928 landscape. Adding an
    orientation sentence to the words did not fix Qwen either - it obeyed
    only its own UI aspect-ratio control and ignored the text - so this
    export states the target size AND tells the human to set the
    provider's own control, relying on neither alone.

    The orientation sentence is repeated on EVERY entry, not stated once
    in the header, because the user's actual gesture is "copy one prompt
    block, paste it" (the same one-at-a-time habit this whole export
    exists to speed up) - a reminder that only lives in a header nobody
    re-copies would silently stop applying the moment someone paste a
    single block instead of the whole file.

    Never touches `entry.prompt` itself - the orientation sentence and
    every heading/rule line are separate list entries the prompt is
    joined with, never string-formatted into it, so the identity
    property (`build_prompt_export_entries`'s own prompt strings are
    byte-identical to `styled_prompt`/`layer_styled_prompt`'s output) is
    preserved all the way out to this rendered text, not just at the
    dataclass layer."""
    style = timeline.metadata.render_style
    frame_aspect = timeline.metadata.frame_aspect
    frame = resolve_render_format(style, frame_aspect=frame_aspect)
    request_frame = resolve_generation_request_format(style, frame)
    aspect = frame.aspect_ratio
    orientation = "landscape" if frame.is_landscape else "portrait"
    orientation_sentence = (
        f"Horizontal landscape image, {aspect} aspect ratio, much wider than it is tall."
        if frame.is_landscape
        else f"Vertical portrait image, {aspect} aspect ratio, much taller than it is wide."
    )

    lines: list[str] = [
        f"IMAGE PROMPTS -- {project_name}",
        f"{len(entries)} images, in scene/shot order.",
        "",
        f"Target size for every image below: {request_frame.width}x{request_frame.height}px"
        f" ({aspect}, {orientation}).",
        "That size is an API parameter the real pipeline sends alongside the prompt --",
        "it does not exist when you paste text into a provider's own chat UI, so the",
        "words in each prompt below are the only signal the provider has. Measured",
        "2026-09-06 against this exact aspect ratio with no orientation words at all:",
        "Grok returned 784x1168 and Qwen returned 1664x928 LANDSCAPE. Adding the",
        "orientation sentence to the words did not fix Qwen either -- it obeyed only",
        f"its own aspect-ratio control. So ALSO set that control to {aspect} /",
        f"{orientation} yourself for every image below. State both; rely on neither",
        "alone.",
        "",
        "Generate every image in ONE provider for this whole film -- mixing providers",
        "re-introduces the exact medium-inconsistency problem this export exists to",
        "remove, just spread across shots instead of concentrated in one.",
        "",
    ]
    rule = "=" * 72
    for entry in entries:
        lines.append(rule)
        lines.append(f"Shot {entry.shot_id}  (scene {entry.scene_id})  --  {_entry_heading(entry)}")
        lines.append(rule)
        lines.append(orientation_sentence)
        lines.append("")
        lines.append(entry.prompt)
        lines.append("")
    return "\n".join(lines)
