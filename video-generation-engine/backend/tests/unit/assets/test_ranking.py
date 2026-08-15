"""Unit tests for the explicit weighted asset ranking function - pure,
no DB, no network (implementation guide, Phase M6 advice: "make ranking
explicit and weighted... log the component scores").

`AssetCandidate.relevance` (the provider's rank-position field) is NOT what
these tests vary to drive the "relevance" component - `rank_candidates` no
longer reads it (see app/assets/relevance.py for why: it's the provider's
result position, not a measure of whether the image matches the query).
Tests that exercise the relevance component instead pass `search_terms` and
vary `title`/`description`, the same real inputs `ResolveAssetsStep` gives
it."""

from app.assets.ranking import rank_candidates
from app.providers.base import AssetCandidate


def _candidate(**overrides) -> AssetCandidate:
    defaults = dict(
        source_id="c1",
        source_url="http://example.test/c1",
        title="a 1930s coal mine photograph",
        licence="cc0",
        width=1080,
        height=1920,
    )
    defaults.update(overrides)
    return AssetCandidate(**defaults)


def test_higher_relevance_wins_all_else_equal():
    low = _candidate(source_id="low", title="a modern city skyline")
    high = _candidate(source_id="high", title="Leuna Werke synthetic fuel plant 1943")
    ranked = rank_candidates(
        [(low, "hash-low"), (high, "hash-high")], search_terms=["Leuna Werke 1943"]
    )
    assert ranked[0].candidate.source_id == "high"


def test_higher_resolution_scores_higher_on_quality():
    small = _candidate(source_id="small", width=200, height=300)
    large = _candidate(source_id="large", width=1080, height=1920)
    ranked = rank_candidates([(small, "hash-small"), (large, "hash-large")])
    assert ranked[0].candidate.source_id == "large"


def test_unknown_dimensions_get_a_neutral_quality_score():
    unknown = _candidate(source_id="unknown", width=None, height=None)
    ranked = rank_candidates([(unknown, "hash-unknown")])
    assert ranked[0].components["quality"] == 0.5


def test_quality_scores_full_for_a_modest_upscale_need():
    """A source needing only a ~1.05x linear upscale to fill the render
    frame (700x1200 against a 720x1280 target) is not visibly degraded -
    full quality score, not a fraction of raw pixel count."""
    modest = _candidate(source_id="modest", width=700, height=1200)
    ranked = rank_candidates([(modest, "hash-modest")])
    assert ranked[0].components["quality"] == 1.0


def test_quality_gives_no_bonus_for_resolution_far_beyond_the_render_target():
    """The fix corrects punishing archival material for being low-res; it
    does not start rewarding a modern source for being needlessly high-res
    either - a 4000x6000 source scores the same 1.0 as one just barely
    big enough for the render."""
    modest = _candidate(source_id="modest", width=700, height=1200)
    huge = _candidate(source_id="huge", width=4000, height=6000)
    ranked = rank_candidates([(modest, "hash-modest"), (huge, "hash-huge")])
    assert ranked[0].components["quality"] == ranked[1].components["quality"] == 1.0


def test_quality_degrades_for_a_source_needing_a_large_upscale():
    """A genuinely tiny source (150x200, a ~5.5x linear upscale for a
    720x1280 render) reads as visibly soft/mushy - low score, but not the
    absolute floor of every other component (never a hard zero)."""
    tiny = _candidate(source_id="tiny", width=150, height=200)
    ranked = rank_candidates([(tiny, "hash-tiny")])
    assert 0.0 < ranked[0].components["quality"] < 0.5


def test_a_low_resolution_archival_photo_no_longer_loses_to_a_high_resolution_irrelevant_one():
    """The regression this fix targets, reproduced directly: measured
    against the live API, a modern high-resolution but off-topic photo
    (here standing in for the real "Polish coal elevator" case) used to
    outrank a lower-resolution but genuinely on-topic archival photo
    purely because of raw pixel count. Same relevance/period/licence on
    both sides; only resolution differs, and it must no longer decide."""
    archival = _candidate(
        source_id="archival",
        title="Leuna Werke synthetic fuel plant archival photograph",
        width=598,
        height=800,
    )
    modern_offtopic = _candidate(
        source_id="modern", title="a modern city skyline", width=3000, height=4000
    )
    ranked = rank_candidates(
        [(archival, "hash-archival"), (modern_offtopic, "hash-modern")],
        search_terms=["Leuna Werke synthetic fuel plant"],
    )
    assert ranked[0].candidate.source_id == "archival"


def test_public_domain_outranks_unknown_licence_all_else_equal():
    pd = _candidate(source_id="pd", licence="public_domain")
    unknown = _candidate(source_id="unknown", licence="some_weird_licence")
    ranked = rank_candidates([(pd, "hash-pd"), (unknown, "hash-unknown")])
    assert ranked[0].candidate.source_id == "pd"


def test_title_matching_historical_period_scores_higher_on_period_match():
    matching = _candidate(source_id="matching", title="1936 Ruhr coal mine")
    unrelated = _candidate(source_id="unrelated", title="a modern skyline")
    ranked = rank_candidates(
        [(matching, "hash-matching"), (unrelated, "hash-unrelated")],
        historical_period="1936-1945",
    )
    assert ranked[0].candidate.source_id == "matching"


def test_no_historical_period_gives_neutral_period_match():
    candidate = _candidate()
    ranked = rank_candidates([(candidate, "hash-1")], historical_period="")
    assert ranked[0].components["period_match"] == 0.5


def test_no_search_terms_gives_a_zero_relevance_component():
    """`rank_candidates` is called on already-gated survivors; without
    `search_terms` (e.g. a caller that never had a query) it must not
    invent a relevance score out of nothing."""
    candidate = _candidate()
    ranked = rank_candidates([(candidate, "hash-1")])
    assert ranked[0].components["relevance"] == 0.0


def test_reuse_penalty_can_flip_the_ranking_despite_higher_relevance():
    reused = _candidate(source_id="reused", title="Leuna Werke synthetic fuel plant 1943")
    fresh = _candidate(source_id="fresh", title="a Leuna factory building")
    ranked = rank_candidates(
        [(reused, "hash-reused"), (fresh, "hash-fresh")],
        search_terms=["Leuna Werke 1943"],
        already_used_hashes=frozenset({"hash-reused"}),
    )
    reused_result = next(r for r in ranked if r.candidate.source_id == "reused")
    fresh_result = next(r for r in ranked if r.candidate.source_id == "fresh")
    assert reused_result.components["relevance"] > fresh_result.components["relevance"]
    assert ranked[0].candidate.source_id == "fresh"
    assert reused_result.components["reuse_penalty"] == 1.0


def test_entity_curated_breaks_a_close_tie_in_its_own_favour():
    """M6.5, A2 (revised after measurement): entity-curated provenance is a
    small, modest component - a tie-breaker among otherwise-similar
    candidates, not an overriding priority tier. Same relevance/quality/
    period/licence on both sides here; only `entity_curated` differs."""
    free_text = _candidate(source_id="free_text", title="Leuna Werke synthetic fuel plant")
    entity = _candidate(
        source_id="entity", title="Leuna Werke synthetic fuel plant", entity_curated=True
    )
    ranked = rank_candidates(
        [(free_text, "hash-free-text"), (entity, "hash-entity")],
        search_terms=["Leuna Werke"],
    )
    assert ranked[0].candidate.source_id == "entity"


def test_entity_curated_does_not_override_a_much_better_free_text_match():
    """The failure mode a live measurement actually found: an unconditional
    entity-curated priority let a poorly-matched entity candidate (here,
    no relation to the query at all) beat an already-correct free-text
    hit. The modest weighted component must not reproduce that - a
    genuinely stronger free-text match still wins outright."""
    strong_free_text = _candidate(
        source_id="strong", title="Leuna Werke Buna synthetic fuel plant 1943"
    )
    weak_entity = _candidate(source_id="weak", title="a modern city skyline", entity_curated=True)
    ranked = rank_candidates(
        [(strong_free_text, "hash-strong"), (weak_entity, "hash-weak")],
        search_terms=["Leuna Werke Buna 1943"],
    )
    assert ranked[0].candidate.source_id == "strong"


def test_results_are_sorted_descending_by_score():
    # Four distinctive query tokens (none in the generic-term list), so each
    # title below matches strictly one more of them than the last - a clean
    # 0/4, 1/4, 2/4, 3/4, 4/4 ladder with no ties to make ordering ambiguous.
    titles = [
        "a modern city skyline",  # matches nothing
        "a Leuna factory building",  # leuna
        "Leuna Werke plant",  # leuna, werke
        "Leuna Werke Buna plant",  # leuna, werke, buna
        "Leuna Werke Buna plant, 1943",  # leuna, werke, buna, 1943
    ]
    candidates = [_candidate(source_id=f"c{i}", title=title) for i, title in enumerate(titles)]
    ranked = rank_candidates(
        [(c, f"hash-{c.source_id}") for c in candidates],
        search_terms=["Leuna Werke Buna 1943"],
    )
    scores = [r.score for r in ranked]
    assert scores == sorted(scores, reverse=True)
    # Not just trivially sorted (`rank_candidates` always sorts) - the
    # order must actually track increasing title/query overlap.
    assert [r.candidate.source_id for r in ranked] == ["c4", "c3", "c2", "c1", "c0"]
