"""`app/script/rewrite.py` - Track D level 3 (motion_new_styles_and_
long_form_videos.md §3.2/§3.3). Pure/fast: no DB, a fake `PlanningLLMProvider`
and a fake `LlmCallRepository` double stand in for the real ones (same
`FakePlanningProvider` shape `tests/unit/planners/helpers.py` already
established, kept local here since this package doesn't otherwise depend
on `planners/`)."""

from app.core.config import settings
from app.providers.base import StructuredCompletion
from app.script.rewrite import ScriptRewriteOutput, _validate_rewrite, rewrite_script

_ORIGINAL = (
    "Germany faced a severe oil shortage because it had very little natural "
    "petroleum reserves in 1943. Sasol and the Fischer-Tropsch process turned "
    "coal into 4.5 million barrels of synthetic fuel that year."
)


class _FakePlanningProvider:
    name = "fake"

    def __init__(self, rewritten_script: str) -> None:
        self._rewritten_script = rewritten_script
        self.calls: list[dict] = []

    async def structured_complete(
        self,
        *,
        system_prompt: str,
        user_content: str,
        response_model: type,
        seed: int | None = None,
    ) -> StructuredCompletion:
        self.calls.append({"system_prompt": system_prompt, "user_content": user_content})
        parsed = ScriptRewriteOutput(rewritten_script=self._rewritten_script)
        return StructuredCompletion(
            parsed=parsed,
            model="fake-planning-model",
            request={"messages": [{"role": "user", "content": user_content}]},
            response=parsed.model_dump(mode="json"),
            input_tokens=10,
            output_tokens=10,
        )


class _FakeLlmCallRepo:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def insert(self, **kwargs) -> None:
        self.calls.append(kwargs)


# ---- _validate_rewrite: pure backstop logic ---------------------------


def test_a_faithful_rewrite_with_more_fragments_is_accepted():
    rewritten = (
        "Germany faced a severe oil shortage. It had very little natural "
        "petroleum reserves in 1943. Sasol and the Fischer-Tropsch process "
        "turned coal into 4.5 million barrels of synthetic fuel that year."
    )
    assert _validate_rewrite(_ORIGINAL, rewritten) == []


def test_a_dropped_number_is_rejected():
    rewritten = _ORIGINAL.replace("4.5 million", "several million")
    reasons = _validate_rewrite(_ORIGINAL, rewritten)
    assert any("numeric tokens changed" in r for r in reasons)
    assert any("4.5" in r for r in reasons)


def test_an_invented_number_is_rejected():
    rewritten = _ORIGINAL + " This continued for 12 more years."
    reasons = _validate_rewrite(_ORIGINAL, rewritten)
    assert any("numeric tokens changed" in r for r in reasons)
    assert any("12" in r for r in reasons)


def test_a_dropped_entity_is_rejected():
    rewritten = _ORIGINAL.replace("Sasol and the Fischer-Tropsch process", "a chemical process")
    reasons = _validate_rewrite(_ORIGINAL, rewritten)
    assert any("capitalised entities dropped" in r for r in reasons)
    assert any("Sasol" in r for r in reasons)
    assert any("Fischer" in r for r in reasons)


def test_a_pronoun_swap_on_second_mention_is_not_penalised():
    """§3.3's own scope: entities are checked as a SET, not a multiset -
    a legitimate rephrase can drop a repeated mention in favour of a
    pronoun without losing the entity itself. Fragment count is bumped
    2 -> 3 here too, so this isolates the entity check rather than
    tripping the separate no-op backstop."""
    original = "Sasol built the plant. Sasol later expanded it in 1955."
    rewritten = "Sasol built the plant. It expanded. The plant grew in 1955."
    assert _validate_rewrite(original, rewritten) == []


def test_common_sentence_initial_words_moving_around_is_not_penalised():
    """Re-splitting sentences legitimately creates/removes capitalised
    words like "The"/"It" at new sentence starts - the stoplist exists
    so ordinary rephrasing doesn't trip the entity check on these."""
    original = "The plant made fuel and it ran for a decade."
    rewritten = "The plant made fuel. It ran for a decade."
    assert _validate_rewrite(original, rewritten) == []


def test_a_rewrite_with_no_more_fragments_is_rejected_as_a_no_op():
    # Same single sentence, no new punctuation - fragment count unchanged.
    rewritten = _ORIGINAL.replace("severe", "serious")
    reasons = _validate_rewrite(_ORIGINAL, rewritten)
    assert any("fragment count did not increase" in r for r in reasons)


def test_a_rewrite_with_fewer_fragments_is_rejected():
    rewritten = "Germany faced a severe oil shortage in 1943, and Sasol's Fischer-Tropsch process turned coal into 4.5 million barrels of synthetic fuel that year."
    reasons = _validate_rewrite(_ORIGINAL, rewritten)
    assert any("fragment count did not increase" in r for r in reasons)


# ---- rewrite_script: the async orchestration ---------------------------


async def test_returns_none_under_dry_run(monkeypatch):
    monkeypatch.setattr(settings, "dry_run", True)
    provider = _FakePlanningProvider(rewritten_script="irrelevant.")
    result = await rewrite_script(
        _ORIGINAL,
        "retention_fast",
        provider=provider,
        llm_call_repo=_FakeLlmCallRepo(),
        project_id="11111111-1111-1111-1111-111111111111",
    )
    assert result is None
    assert provider.calls == []


async def test_returns_none_when_no_provider_is_configured(monkeypatch):
    monkeypatch.setattr(settings, "dry_run", False)
    result = await rewrite_script(
        _ORIGINAL,
        "retention_fast",
        provider=None,
        llm_call_repo=_FakeLlmCallRepo(),
        project_id="11111111-1111-1111-1111-111111111111",
    )
    assert result is None


async def test_returns_none_for_an_empty_script(monkeypatch):
    monkeypatch.setattr(settings, "dry_run", False)
    provider = _FakePlanningProvider(rewritten_script="irrelevant.")
    result = await rewrite_script(
        "   ",
        "retention_fast",
        provider=provider,
        llm_call_repo=_FakeLlmCallRepo(),
        project_id="11111111-1111-1111-1111-111111111111",
    )
    assert result is None
    assert provider.calls == []


async def test_an_accepted_rewrite_records_the_llm_call_and_re_runs_feasibility(monkeypatch):
    monkeypatch.setattr(settings, "dry_run", False)
    rewritten = (
        "Germany faced a severe oil shortage. It had very little natural "
        "petroleum reserves in 1943. Sasol and the Fischer-Tropsch process "
        "turned coal into 4.5 million barrels of synthetic fuel that year."
    )
    provider = _FakePlanningProvider(rewritten_script=rewritten)
    llm_call_repo = _FakeLlmCallRepo()

    result = await rewrite_script(
        _ORIGINAL,
        "retention_fast",
        provider=provider,
        llm_call_repo=llm_call_repo,
        project_id="11111111-1111-1111-1111-111111111111",
    )

    assert result is not None
    assert result.accepted is True
    assert result.rejection_reasons == []
    assert result.rewritten_script == rewritten
    assert result.rewritten_fragment_count > result.original_fragment_count
    assert result.feasibility is not None
    assert len(provider.calls) == 1
    assert "retention_fast" in provider.calls[0]["user_content"]
    assert len(llm_call_repo.calls) == 1
    assert llm_call_repo.calls[0]["agent"] == "script_rewrite"


async def test_a_rejected_rewrite_is_still_returned_with_reasons(monkeypatch):
    monkeypatch.setattr(settings, "dry_run", False)
    # Drops "4.5 million" - a real number - and adds no new fragments.
    bad_rewrite = (
        "Germany faced a severe oil shortage because it had very little natural petroleum."
    )
    provider = _FakePlanningProvider(rewritten_script=bad_rewrite)

    result = await rewrite_script(
        _ORIGINAL,
        "retention_fast",
        provider=provider,
        llm_call_repo=_FakeLlmCallRepo(),
        project_id="11111111-1111-1111-1111-111111111111",
    )

    assert result is not None
    assert result.accepted is False
    assert result.rejection_reasons != []
    assert result.rewritten_script == bad_rewrite
