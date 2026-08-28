"""Caption romanizer: validator (pure) and planner (fake provider, no DB).

No live Postgres, no live LLM. `--noconftest` is the only safe way to
run this file (caption_romanization.md §4, §11.7).

§11: the LLM does plain 1:1 transliteration only (`CaptionRomanizerOutput`
is a bare `caption_text: str`, no `covers`). Numeral merging is a
deterministic pass over the validated output (`numerals.py`, tested
separately in `test_caption_numerals.py`). This file tests the
1:1 validator and the planner's end-to-end wiring, including that the
numeral pass actually runs after a clean LLM response.
"""

from app.core.errors import TransientError
from app.planners.caption_romanizer.planner import (
    CaptionRomanizer,
    contains_devanagari,
    needs_romanization,
    romanization_violations,
)
from app.planners.caption_romanizer.schemas import CaptionRomanizerOutput
from app.providers.base import StructuredCompletion
from app.schemas.timeline import Scene, Shot, ShotIntent

from .helpers import FakePlanningProvider

_PROJECT_ID = "00000000-0000-0000-0000-000000000001"

_SRC = "एक Indian guru जिसके पास 90 Rolls-Royce थीं।"
_GOOD = "ek Indian guru jiske paas 90 Rolls-Royce theen."

_YEAR_SRC = "उन्नीस सौ इकतीस में उनका India में जन्म हुआ।"
_YEAR_1TO1 = "unnis sau ikatees mein unka India mein janm hua."
_YEAR_CAP = "1931 mein unka India mein janm hua."

_2026_SRC = "दो हजार छब्बीस।"
_2026_1TO1 = "do hazaar chhabbis."
_2026_CAP = "2026."


def _out(text: str) -> CaptionRomanizerOutput:
    return CaptionRomanizerOutput(caption_text=text)


_GOOD_OUT = _out(_GOOD)


class _FakeLlmCallRepo:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def insert(self, **kwargs) -> None:
        self.calls.append(kwargs)


def _scene(
    narration_text: str,
    *,
    scene_id: str = "sc_01",
    caption_text: str | None = None,
    caption_word_groups: list[int] | None = None,
) -> Scene:
    return Scene(
        id=scene_id,
        order=0,
        title="t",
        narration_text=narration_text,
        duration_s=3.0,
        caption_text=caption_text,
        caption_word_groups=caption_word_groups,
        shots=[Shot(id="sh_01", order=0, intent=ShotIntent.EXPLAIN, duration_s=3.0)],
    )


# ---- validator (pure) -----------------------------------------------------


def test_word_count_change_is_a_violation():
    out = _out("ek Indian guru")
    reasons = romanization_violations(_SRC, out)
    assert any("word count changed: 8 -> 3" in r for r in reasons)


def test_latin_word_altered_is_a_violation():
    out = _out("ek indiya guru jiske paas 90 Rolls-Royce theen.")
    reasons = romanization_violations(_SRC, out)
    assert any("Latin word 'Indian' was altered to 'indiya'" in r for r in reasons)


def test_residual_devanagari_is_a_violation():
    out = _out("ek Indian गुरु jiske paas 90 Rolls-Royce theen.")
    reasons = romanization_violations(_SRC, out)
    assert any("output still contains Devanagari" in r for r in reasons)
    assert contains_devanagari("ek Indian गुरु jiske paas 90 Rolls-Royce theen.")


def test_clean_romanization_has_no_violations():
    assert romanization_violations(_SRC, _GOOD_OUT) == []


def test_danda_left_in_place_is_devanagari():
    # `।` is U+0964, inside the Devanagari block. The prompt converts it
    # to a period; the validator does not special-case it — leftover
    # danda fails the residual-Devanagari check.
    out = _out("ek Indian guru jiske paas 90 Rolls-Royce theen।")
    reasons = romanization_violations(_SRC, out)
    assert any("output still contains Devanagari" in r for r in reasons)


def test_a_merged_llm_output_is_now_a_word_count_violation():
    # §11 withdrew §10.3's `covers` contract. The LLM merging three
    # words into one digit token itself would now just look like a
    # dropped word count — merging is no longer a shape the LLM's
    # output can express at all.
    out = _out("1931 mein unka India mein janm hua.")
    reasons = romanization_violations(_YEAR_SRC, out)
    assert any("word count changed: 9 -> 7" in r for r in reasons)


def test_latin_only_scene_does_not_need_romanization():
    scene = _scene("Osho died in 1990 in Pune.")
    assert not needs_romanization(scene)


def test_scene_romanized_under_the_current_contract_does_not_need_romanization():
    # Groups present - even all-ones, meaning "nothing to merge" - is a
    # scene that has been through the romanization pass. Leave it alone.
    scene = _scene(_SRC, caption_text=_GOOD, caption_word_groups=[1] * len(_GOOD.split()))
    assert not needs_romanization(scene)


def test_scene_romanized_before_grouping_existed_needs_romanization_again():
    """Pre-§10 upgrade path. A scene romanized before grouping existed
    has `caption_text` but no `caption_word_groups`, so it can never
    merge a spelled-out Hindi numeral into digits - it would keep
    showing `unnis sau ikatees` beside a `1990: Osho Dies` text card. A
    missing group list means "not romanized under the current
    contract", not "already done".

    Without this, re-running the backfill over an already-romanized
    project silently skips every scene and reports success."""
    scene = _scene(_SRC, caption_text=_GOOD, caption_word_groups=None)
    assert needs_romanization(scene)


def test_digits_already_in_narration_are_not_required_to_change():
    src = "1990 में 58 की age में Osho की मौत हो गई।"
    out = _out("1990 mein 58 ki age mein Osho ki maut ho gayi.")
    assert romanization_violations(src, out) == []


# ---- planner (fake provider, no DB) ----------------------------------------


async def test_plan_writes_caption_text_on_a_clean_response():
    provider = FakePlanningProvider(responses=[_GOOD_OUT])
    repo = _FakeLlmCallRepo()
    planner = CaptionRomanizer(provider, repo)  # type: ignore[arg-type]

    scenes = await planner.plan(project_id=_PROJECT_ID, scenes=[_scene(_SRC)])

    assert scenes[0].caption_text == _GOOD
    assert scenes[0].caption_word_groups == [1] * len(_GOOD.split())
    assert scenes[0].narration_text == _SRC
    assert len(provider.calls) == 1
    assert repo.calls[0]["agent"] == "caption_romanizer"


async def test_plan_merges_a_numeral_run_from_plain_1to1_llm_output():
    """The LLM comes back with plain 1:1 transliteration (no merging —
    §11). The planner's own deterministic numeral pass, not the LLM,
    collapses `unnis sau ikatees` into `1931`."""
    provider = FakePlanningProvider(responses=[_out(_YEAR_1TO1)])
    planner = CaptionRomanizer(provider, _FakeLlmCallRepo())  # type: ignore[arg-type]

    scenes = await planner.plan(project_id=_PROJECT_ID, scenes=[_scene(_YEAR_SRC)])

    assert scenes[0].caption_text == _YEAR_CAP
    assert scenes[0].caption_word_groups == [3, 1, 1, 1, 1, 1, 1]


async def test_plan_pins_2026_not_2006():
    """The exact §10 defect this exists to make impossible: a real run
    produced `2006` for `दो हजार छब्बीस`. Pinned as a literal."""
    provider = FakePlanningProvider(responses=[_out(_2026_1TO1)])
    planner = CaptionRomanizer(provider, _FakeLlmCallRepo())  # type: ignore[arg-type]

    scenes = await planner.plan(project_id=_PROJECT_ID, scenes=[_scene(_2026_SRC)])

    assert scenes[0].caption_text == _2026_CAP
    assert scenes[0].caption_text != "2006."
    assert scenes[0].caption_word_groups == [3]


async def test_plan_skips_latin_only_scenes_without_calling_the_provider():
    provider = FakePlanningProvider(responses=[])
    planner = CaptionRomanizer(provider, _FakeLlmCallRepo())  # type: ignore[arg-type]

    scenes = await planner.plan(
        project_id=_PROJECT_ID, scenes=[_scene("Osho died in 1990 in Pune.")]
    )

    assert scenes[0].caption_text is None
    assert scenes[0].caption_word_groups is None
    assert provider.calls == []


async def test_plan_leaves_caption_text_none_after_repair_still_fails(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "planner_max_repair_attempts", 1)
    bad = _out("ek Indian guru")
    provider = FakePlanningProvider(responses=[bad, bad])
    planner = CaptionRomanizer(provider, _FakeLlmCallRepo())  # type: ignore[arg-type]

    scenes = await planner.plan(project_id=_PROJECT_ID, scenes=[_scene(_SRC)])

    assert scenes[0].caption_text is None
    assert scenes[0].caption_word_groups is None
    assert scenes[0].narration_text == _SRC
    assert len(provider.calls) == 2
    assert "word count changed" in provider.calls[1]["user_content"]


async def test_plan_repairs_once_then_succeeds():
    bad = _out("ek Indian guru")
    provider = FakePlanningProvider(responses=[bad, _GOOD_OUT])
    planner = CaptionRomanizer(provider, _FakeLlmCallRepo())  # type: ignore[arg-type]

    scenes = await planner.plan(project_id=_PROJECT_ID, scenes=[_scene(_SRC)])

    assert scenes[0].caption_text == _GOOD
    assert len(provider.calls) == 2


async def test_plan_does_not_raise_permanent_error_on_validation_failure(monkeypatch):
    """§3.5: a captions cosmetic miss must not destroy the run."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "planner_max_repair_attempts", 1)
    bad = _out("ek Indian guru")
    provider = FakePlanningProvider(responses=[bad, bad])
    planner = CaptionRomanizer(provider, _FakeLlmCallRepo())  # type: ignore[arg-type]

    scenes = await planner.plan(project_id=_PROJECT_ID, scenes=[_scene(_SRC)])
    assert scenes[0].caption_text is None
    # And it really was a PermanentError internally, not a skipped call.
    assert len(provider.calls) == 2


class _BoomProvider:
    name = "fake"

    async def structured_complete(self, **kwargs):
        raise TransientError("rate limited")


async def test_plan_propagates_transient_error(monkeypatch):
    from app.core.config import settings

    # One attempt, no backoff sleep — this test is about propagation,
    # not the gather's retry loop.
    monkeypatch.setattr(settings, "bounded_gather_max_attempts", 1)
    planner = CaptionRomanizer(_BoomProvider(), _FakeLlmCallRepo())  # type: ignore[arg-type]
    try:
        await planner.plan(project_id=_PROJECT_ID, scenes=[_scene(_SRC)])
    except TransientError:
        return
    raise AssertionError("expected TransientError to propagate")


class _KeyedProvider:
    """Succeeds for one scene's narration, fails validation for the other.
    Call-order independent, so bounded_gather concurrency cannot flake."""

    name = "fake"

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def structured_complete(
        self,
        *,
        system_prompt: str,
        user_content: str,
        response_model: type,
        seed: int | None = None,
    ) -> StructuredCompletion:
        self.calls.append({"user_content": user_content})
        parsed = _out("ek Indian guru") if "FAILMARKER" in user_content else _GOOD_OUT
        return StructuredCompletion(
            parsed=parsed,
            model="fake-planning-model",
            request={"messages": [{"role": "user", "content": user_content}]},
            response=parsed.model_dump(mode="json"),
            input_tokens=1,
            output_tokens=1,
        )


async def test_plan_isolates_failure_to_the_failing_scene(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "planner_max_repair_attempts", 1)
    provider = _KeyedProvider()
    planner = CaptionRomanizer(provider, _FakeLlmCallRepo())  # type: ignore[arg-type]
    fail_src = "FAILMARKER एक Indian guru जिसके पास 90 Rolls-Royce थीं।"
    scenes = [
        _scene(fail_src, scene_id="sc_fail"),
        _scene(_SRC, scene_id="sc_ok"),
    ]

    out = await planner.plan(project_id=_PROJECT_ID, scenes=scenes)

    by_id = {s.id: s for s in out}
    assert by_id["sc_fail"].caption_text is None
    assert by_id["sc_ok"].caption_text == _GOOD
    assert by_id["sc_fail"].narration_text == fail_src
    assert by_id["sc_ok"].narration_text == _SRC
