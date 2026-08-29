"""OpenAI planning provider (ADR-003, M5). The only file in this codebase
that imports the `openai` package - every planner depends on
`PlanningLLMProvider` (app/providers/base.py), never on this class or the
SDK directly.

Structured output is forced via `response_format=<PydanticModel>`
(strict JSON-schema mode) rather than asking nicely in the prompt and
hoping - implementation guide, Phase M5 advice.
"""

import base64
import io
from typing import Any, TypeVar

from openai import (
    APIConnectionError,
    APITimeoutError,
    AsyncOpenAI,
    BadRequestError,
    InternalServerError,
    OpenAIError,
    RateLimitError,
)
from openai.types.chat import (
    ChatCompletionContentPartImageParam,
    ChatCompletionContentPartTextParam,
    ChatCompletionMessageParam,
    ChatCompletionSystemMessageParam,
    ChatCompletionUserMessageParam,
)
from PIL import Image
from pydantic import BaseModel

from app.core.config import settings
from app.core.errors import PermanentError, TransientError
from app.core.logging import get_logger
from app.providers.base import (
    ConstraintCheckRequest,
    ConstraintVerdict,
    DepictionCheckRequest,
    DepictionVerdict,
    StructuredCompletion,
    SubjectFocal,
    SubjectFocalRequest,
)

logger = get_logger(__name__)

ResponseModelT = TypeVar("ResponseModelT", bound=BaseModel)

_TRANSIENT_ERRORS = (RateLimitError, APITimeoutError, APIConnectionError, InternalServerError)

# Model ids observed to reject a custom `temperature` (see the fallback in
# `structured_complete`). Learned at runtime from OpenAI's own error rather
# than hardcoded, so it stays correct when the configured model changes -
# but remembered, so the doomed first attempt is paid ONCE per process
# instead of on every single planner call. Without this, a 5-scene script
# costs ~11 wasted round-trips and doubles planning latency.
_MODELS_REJECTING_TEMPERATURE: set[str] = set()



def _downscale_for_focal(image: bytes, content_type: str, max_px: int) -> tuple[bytes, str]:
    """Shrink an image to `max_px` on its longest edge for vision calls.

    Shared by `locate_subject` (`focal_image_max_px`) and
    `check_depiction` (`depiction_image_max_px`) — same resize
    (longest-edge, LANCZOS, JPEG q88). Name kept for the focal call that
    introduced it; depiction re-uses it after its own re-measurement
    (output_quality_pass.md §14.7 / P-OQ-15.4).

    Never raises: an unreadable or already-small image is returned
    untouched (a vision hint/gate miss is not worth failing a resolve).
    """
    if max_px <= 0:
        return image, content_type
    try:
        with Image.open(io.BytesIO(image)) as im:
            if max(im.size) <= max_px:
                return image, content_type
            im = im.convert("RGB")
            scale = max_px / max(im.size)
            im = im.resize(
                (max(1, round(im.width * scale)), max(1, round(im.height * scale))),
                Image.LANCZOS,
            )
            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=88)
            return buf.getvalue(), "image/jpeg"
    except (OSError, ValueError) as exc:
        logger.warning("vision.downscale_failed", extra={"error": str(exc)[:200]})
        return image, content_type

class OpenAIPlanningProvider:
    name = "openai"

    def __init__(self, client: AsyncOpenAI | None = None, *, model: str | None = None) -> None:
        self._client = client or AsyncOpenAI(
            api_key=settings.openai_api_key, organization=settings.openai_org_id
        )
        # Default is the planning model every other agent uses. The
        # caption romanizer passes `settings.openai_planning_model_cheap`
        # — mechanical transliteration, no reason to spend the terra
        # model (caption_romanization.md §2.4).
        self._model = model or settings.openai_planning_model

    async def _parse(
        self,
        *,
        messages: list[dict[str, str]],
        response_model: type[ResponseModelT],
        seed: int | None,
        temperature: float | None,
    ) -> Any:
        kwargs: dict[str, Any] = {
            "model": self._model,
            "seed": seed,
            "messages": messages,
            "response_format": response_model,
        }
        if temperature is not None:
            kwargs["temperature"] = temperature
        return await self._client.chat.completions.parse(**kwargs)

    async def structured_complete(
        self,
        *,
        system_prompt: str,
        user_content: str,
        response_model: type[ResponseModelT],
        seed: int | None = None,
    ) -> StructuredCompletion:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]
        model = self._model
        # Skip the doomed attempt entirely once this model has already told
        # us it won't take a custom temperature.
        temperature = (
            None if model in _MODELS_REJECTING_TEMPERATURE else settings.openai_temperature
        )
        try:
            try:
                completion = await self._parse(
                    messages=messages,
                    response_model=response_model,
                    seed=seed,
                    temperature=temperature,
                )
            except BadRequestError as exc:
                # Reasoning-tier models (o-series, gpt-5.x) reject any
                # temperature other than their fixed default and report it
                # via this exact param/code pair - fall back to the
                # model's default rather than hardcoding a model allowlist
                # that will be stale the next time the configured model
                # changes. Remembering the answer keeps that discovery to
                # one wasted request per process rather than one per call.
                if temperature is not None and exc.param == "temperature":
                    _MODELS_REJECTING_TEMPERATURE.add(model)
                    logger.info(
                        "openai.temperature_unsupported_falling_back_to_default",
                        extra={"model": model},
                    )
                    completion = await self._parse(
                        messages=messages,
                        response_model=response_model,
                        seed=seed,
                        temperature=None,
                    )
                else:
                    raise PermanentError(f"openai error: {exc}") from exc
        except _TRANSIENT_ERRORS as exc:
            raise TransientError(f"openai transient error: {exc}") from exc
        except OpenAIError as exc:
            raise PermanentError(f"openai error: {exc}") from exc

        choice = completion.choices[0]
        if choice.message.refusal:
            raise PermanentError(f"openai refused the request: {choice.message.refusal}")
        parsed = choice.message.parsed
        if parsed is None:
            raise PermanentError("openai did not return parseable structured output")

        usage = completion.usage
        return StructuredCompletion(
            parsed=parsed,
            model=completion.model,
            request={"model": model, "messages": messages},
            response=choice.message.model_dump(mode="json"),
            input_tokens=usage.prompt_tokens if usage else None,
            output_tokens=usage.completion_tokens if usage else None,
        )

    async def check_constraints(self, request: ConstraintCheckRequest) -> StructuredCompletion:
        """M6.5, A12 - `VisionConstraintProvider`. Same structured-output
        call shape as `structured_complete` above, but with an image
        content block attached; a separate, smaller model
        (`settings.openai_vision_model`) rather than the planning model,
        since vision support isn't guaranteed on every model choice and
        this is a mechanical check, not creative judgement."""
        image_b64 = base64.b64encode(request.image).decode("ascii")
        data_url = f"data:{request.image_content_type};base64,{image_b64}"
        constraints_text = "\n".join(f"- {c}" for c in request.constraints)

        system_message: ChatCompletionSystemMessageParam = {
            "role": "system",
            "content": (
                "You check a generated image against a fixed list of hard "
                "creative constraints. Flag a violation only if it is "
                "genuinely visible in the image - do not invent one, and do "
                "not flag a constraint the image plainly satisfies."
            ),
        }
        text_part: ChatCompletionContentPartTextParam = {
            "type": "text",
            "text": (
                f"Shot prompt this image was generated from: {request.shot_prompt}\n\n"
                f"Constraints this image must not violate:\n{constraints_text}"
            ),
        }
        image_part: ChatCompletionContentPartImageParam = {
            "type": "image_url",
            "image_url": {"url": data_url},
        }
        user_message: ChatCompletionUserMessageParam = {
            "role": "user",
            "content": [text_part, image_part],
        }
        messages: list[ChatCompletionMessageParam] = [system_message, user_message]
        try:
            completion = await self._client.chat.completions.parse(
                model=settings.openai_vision_model,
                messages=messages,
                response_format=ConstraintVerdict,
            )
        except _TRANSIENT_ERRORS as exc:
            raise TransientError(f"openai vision check transient error: {exc}") from exc
        except OpenAIError as exc:
            raise PermanentError(f"openai vision check error: {exc}") from exc

        choice = completion.choices[0]
        if choice.message.refusal:
            raise PermanentError(f"openai refused the vision check: {choice.message.refusal}")
        parsed = choice.message.parsed
        if parsed is None:
            raise PermanentError("openai did not return a parseable constraint verdict")

        usage = completion.usage
        # `request` deliberately omits the base64 image data URI - it can be
        # megabytes, and the point of the audit row (like every other
        # `llm_call`) is "what was asked and what came back", not a second
        # copy of the image bytes themselves. (Not "it's already on disk" -
        # a REJECTED attempt's bytes are deliberately never written anywhere;
        # this is purely about not bloating the `llm_call` audit row.)
        return StructuredCompletion(
            parsed=parsed,
            model=completion.model,
            request={
                "model": settings.openai_vision_model,
                "shot_prompt": request.shot_prompt,
                "constraints": request.constraints,
            },
            response=choice.message.model_dump(mode="json"),
            input_tokens=usage.prompt_tokens if usage else None,
            output_tokens=usage.completion_tokens if usage else None,
        )

    async def check_depiction(self, request: DepictionCheckRequest) -> StructuredCompletion:
        """M6.5, A16 -> A30 -> A30a - `VisionConstraintProvider`'s other
        half, recalibrated twice after live measurement against the real
        Hindi benchmark - both rounds measured, not guessed.

        Round 1 (original A30): "does this image genuinely depict the
        specific subject searched for" rejected two genuinely correct
        images - a real Bundesarchiv Leuna photograph and a real
        Fischer-Tropsch diagram - because nothing in the PIXELS can
        confirm a specific NAMED place or event; that identity lives in
        an archive's catalogue metadata, invisible to a vision model.

        Round 2 (first A30a draft): loosened to "is this confidently a
        different KIND of subject" - correctly restored both of those,
        but measured to ALSO let back in two of the five originally-
        eliminated wrong picks (a map of Greece for a "German WWII
        resource map" query; modern re-enactors on motorcycles for
        "German tanks") - the model's own recorded reasoning called a
        map "consistent with the general theme of a resource map"
        regardless of which COUNTRY it showed, and called motorcycles
        "plausibly relat[ed] to wartime Germany" despite showing no
        tanks at all. Vague thematic resemblance, exactly what the
        original A30 prompt (correctly) refused to accept, crept back in
        under the looser wording.

        This version narrows the question with concrete positive and
        negative examples grounded in those exact measured cases: reject
        on visible, CHECKABLE subject-matter facts (which country/region
        a map shows, which general type of object/vehicle/structure is
        present, whether the material is genuinely archival or a modern/
        re-enactment scene) - these are things pixels really can answer.
        Do not reject merely because the SPECIFIC NAMED identity (this
        exact plant, as opposed to a similar one) cannot be confirmed -
        that is a catalogue-metadata question, not a pixel one. Biased
        toward keeping only within that narrower band: a false reject
        permanently discards a real, usable image; a false accept costs
        one image a human still sees at the approval gate and can
        override. Same model (`settings.openai_vision_model`) and call
        shape as `check_constraints`, its own prompt for the same reason
        as before - a different question from "does this violate a fixed
        rule".

        Image longest edge is capped at `settings.depiction_image_max_px`
        (1024 as of P-OQ-15.4): 512 flipped a full-res reject into an
        accept on a process diagram; 1024 held with 0 flips."""
        shrunk, shrunk_type = _downscale_for_focal(
            request.image, request.image_content_type, settings.depiction_image_max_px
        )
        image_b64 = base64.b64encode(shrunk).decode("ascii")
        data_url = f"data:{shrunk_type};base64,{image_b64}"

        system_message: ChatCompletionSystemMessageParam = {
            "role": "system",
            "content": (
                "You check whether an image's actual visible content is a "
                "plausible match for a shot's subject matter. Reject when the "
                "image is CONFIDENTLY wrong on visible, checkable facts: the "
                "general region, country, or place shown; the general type of "
                "object, vehicle, or structure shown; or the general era "
                "(genuinely archival material versus a clearly modern scene "
                "or costumed re-enactment). Do NOT reject merely because you "
                "cannot confirm this is the SPECIFIC NAMED site, plant, or "
                "event that was searched for - that level of identity lives "
                "in an archive's catalogue, not in the pixels, and is not "
                "something you can verify by looking.\n\n"
                "Examples of what TO reject (checkable from the pixels "
                "alone):\n"
                "- A map of the wrong country or region (e.g. a map of "
                "Greece when a map of wartime Germany or Europe was wanted).\n"
                "- The wrong general type of vehicle, object, or structure "
                "(e.g. motorcycles when tanks were wanted; a burning ship at "
                "sea when a resource map was wanted; a ruined, abandoned "
                "structure when an operating industrial plant was wanted).\n"
                "- A clearly modern photograph, or a costumed re-enactment, "
                "when genuine archival-era material was wanted.\n"
                "- A generic building or scene with no visible resemblance to "
                "the requested structure (e.g. plain modern offices when oil "
                "storage tanks were wanted).\n\n"
                "Examples of what NOT to reject (unverifiable from pixels "
                "alone, never a reason to reject on their own):\n"
                "- An industrial photograph that could plausibly be the named "
                "plant, even though nothing in the image proves it is THAT "
                "specific site rather than a similar one.\n"
                "- A process diagram depicting the right general chemistry or "
                "process, even if its exact layout, labelling, or style "
                "differs from what was imagined.\n\n"
                "A false rejection permanently discards a real, usable image; "
                "a false acceptance only costs one image a human will see at "
                "the approval gate and can still override."
            ),
        }
        text_part: ChatCompletionContentPartTextParam = {
            "type": "text",
            "text": (
                f"The shot this image is meant to illustrate: {request.shot_prompt}\n\n"
                f"It was found searching for: {request.search_subject} - treat this "
                "as context for the general kind of thing being looked for, not as "
                "a specific identity you need to confirm.\n\n"
                "Is this image CONFIDENTLY wrong on visible, checkable subject-matter "
                "facts (region/place, object/vehicle/structure type, or era) - not "
                "merely unconfirmed as the exact named subject?"
            ),
        }
        image_part: ChatCompletionContentPartImageParam = {
            "type": "image_url",
            "image_url": {"url": data_url},
        }
        user_message: ChatCompletionUserMessageParam = {
            "role": "user",
            "content": [text_part, image_part],
        }
        messages: list[ChatCompletionMessageParam] = [system_message, user_message]
        try:
            completion = await self._client.chat.completions.parse(
                model=settings.openai_vision_model,
                messages=messages,
                response_format=DepictionVerdict,
            )
        except _TRANSIENT_ERRORS as exc:
            raise TransientError(f"openai depiction check transient error: {exc}") from exc
        except OpenAIError as exc:
            raise PermanentError(f"openai depiction check error: {exc}") from exc

        choice = completion.choices[0]
        if choice.message.refusal:
            raise PermanentError(f"openai refused the depiction check: {choice.message.refusal}")
        parsed = choice.message.parsed
        if parsed is None:
            raise PermanentError("openai did not return a parseable depiction verdict")

        usage = completion.usage
        return StructuredCompletion(
            parsed=parsed,
            model=completion.model,
            request={
                "model": settings.openai_vision_model,
                "shot_prompt": request.shot_prompt,
                "search_subject": request.search_subject,
            },
            response=choice.message.model_dump(mode="json"),
            input_tokens=usage.prompt_tokens if usage else None,
            output_tokens=usage.completion_tokens if usage else None,
        )

    async def locate_subject(self, request: SubjectFocalRequest) -> StructuredCompletion:
        """Where is the main subject (OQ-2, re-cut 2026-08-29)?

        Its own call, on its own model (`settings.openai_focal_model`),
        for two measured reasons — see `SubjectFocal` and
        `output_quality_pass.md` §14 for the evidence:

        - `settings.openai_vision_model` (gpt-4o-mini) cannot do this.
          On real assets it aimed at the kart instead of the driver, at
          the wrong car of two, and at empty track beside the pack.
        - The plausibility gate this used to ride along with was
          calibrated twice (A30/A30a) against that cheap model. Sharing
          one call meant either paying the strong model for the gate or
          silently re-opening a calibration. Splitting costs one extra
          call per BOUND shot (not per candidate) and leaves the gate
          exactly as measured.

        The prompt forces NAME -> WORDS -> NUMBERS. That ordering is not
        style: asking for coordinates alone returns 0.5,0.5 (11 of 12
        real sidecars did). `SubjectFocal` has no defaults, so a model
        that declines to answer raises rather than fabricating a centre.
        """
        shrunk, shrunk_type = _downscale_for_focal(
            request.image, request.image_content_type, settings.focal_image_max_px
        )
        image_b64 = base64.b64encode(shrunk).decode("ascii")
        data_url = f"data:{shrunk_type};base64,{image_b64}"
        system_message: ChatCompletionSystemMessageParam = {
            "role": "system",
            "content": (
                "A documentary editor needs to know what to point the camera at in "
                "this photograph, so a slow push or punch-in lands on the subject "
                "rather than on the geometric middle of the frame.\n\n"
                "First NAME the single most important subject - a person's face, a "
                "vehicle, a labelled structure. Then say in WORDS where it sits in "
                "the frame. Only then give focal_x and focal_y, normalised 0..1 with "
                "the origin at the top-left, consistent with the words you just "
                "wrote.\n\n"
                "Most photographs are NOT centred. 0.5,0.5 should be rare, and only "
                "when the subject genuinely is dead centre."
            ),
        }
        image_part: ChatCompletionContentPartImageParam = {
            "type": "image_url",
            "image_url": {"url": data_url},
        }
        text_part: ChatCompletionContentPartTextParam = {
            "type": "text",
            "text": "Name the main subject of this image and give its location.",
        }
        user_message: ChatCompletionUserMessageParam = {
            "role": "user",
            "content": [text_part, image_part],
        }
        messages: list[ChatCompletionMessageParam] = [system_message, user_message]
        try:
            completion = await self._client.chat.completions.parse(
                model=settings.openai_focal_model,
                messages=messages,
                response_format=SubjectFocal,
            )
        except _TRANSIENT_ERRORS as exc:
            raise TransientError(f"openai subject-focal transient error: {exc}") from exc
        except OpenAIError as exc:
            raise PermanentError(f"openai subject-focal error: {exc}") from exc

        choice = completion.choices[0]
        if choice.message.refusal:
            raise PermanentError(f"openai refused the subject-focal call: {choice.message.refusal}")
        parsed = choice.message.parsed
        if parsed is None:
            raise PermanentError("openai did not return a parseable subject focal")

        usage = completion.usage
        return StructuredCompletion(
            parsed=parsed,
            model=completion.model,
            request={"model": settings.openai_focal_model},
            response=choice.message.model_dump(mode="json"),
            input_tokens=usage.prompt_tokens if usage else None,
            output_tokens=usage.completion_tokens if usage else None,
        )
