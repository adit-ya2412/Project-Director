"""Real relevance, computed - not the provider's search-result position.

Both `WikimediaAssetProvider` and `PexelsAssetProvider` set
`AssetCandidate.relevance` to `max(0.3, 1.0 - 0.05 * rank)` - a function of
where the provider chose to put the result, not of whether the image has
anything to do with the query. A crucifixion painting returned first scores
a perfect 1.0 on that field. This module replaces it with a genuine text
match between the shot's search query and the candidate's own metadata
(title + description), and is the one thing `ResolveAssetsStep` gates on
before a candidate is even downloaded (implementation guide, Phase M6
advice: "licence checking is a hard gate, not a ranking factor" - the same
principle applies here: a candidate that fails the relevance gate is
discarded, never merely deprioritised).

## The rule, and why

Plain "do any words overlap" matching is not enough - two real failures from
a production run prove it:

- `South Africa oil embargo` matched a map titled "...Control over South
  America 1700..." - both strings share the word "South".
- `Ruhr coal mine 1940` matched "BNR bogie coal hopper wagon 1921" - both
  share the word "coal".

"South" and "coal" are ordinary English words that turn up constantly
across unrelated documents; matching on them alone is not evidence of
subject overlap. Meanwhile the two matches that WERE correct in the same
run worked precisely because a rare, specific term survived into the
candidate's title: "Leuna" (a real chemical-plant name) and "Sasol" /
"Secunda" (a real company and town name). Those terms are informative
*because* they are rare - almost nothing else on Commons is called
"Leuna".

Lacking corpus statistics to compute real IDF, `_GENERIC_TERMS` is a small,
explicit stand-in: compass directions, continents, and the generic
photo/industrial nouns ("map", "coal", "mine", "rail", "tank", "yard"...)
that recur across huge numbers of unrelated archival titles. Any token in
that set - or a stopword - counts for a quarter as much as an ordinary
token when computing overlap. A single shared generic term can no longer
carry a match; a single shared *distinctive* term (a proper noun, a plant
name, a rare word) can, exactly like the two real matches that worked.
"""

import re
import unicodedata

from app.core.config import settings
from app.providers.base import AssetCandidate

# Function words: zero signal either way, dropped outright rather than
# down-weighted. A few common non-English function words are included
# because Commons titles/descriptions are frequently in German, French, or
# Dutch (the shot's own query is not) - "aus" or "der" surviving as a
# "distinctive" token would be an accidental, meaningless match.
_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "been",
        "by",
        "for",
        "from",
        "in",
        "into",
        "is",
        "it",
        "near",
        "of",
        "on",
        "or",
        "over",
        "that",
        "the",
        "this",
        "to",
        "under",
        "was",
        "were",
        "with",
        "aus",
        "der",
        "die",
        "das",
        "und",
        "de",
        "la",
        "le",
        "un",
        "une",
        "et",
        "van",
        "een",
    }
)

# Generic terms: real content words, but common enough across unrelated
# archival material that one of them matching alone is not evidence of
# subject overlap (see module docstring - the "South" and "coal" traps).
# Down-weighted, not dropped - several of these matching together is still
# real signal.
_GENERIC_TERMS = frozenset(
    {
        # compass directions / continents - too broad to identify a specific
        # place on their own
        "north",
        "south",
        "east",
        "west",
        "america",
        "africa",
        "asia",
        "europe",
        "australia",
        "african",
        "american",
        "european",
        "asian",
        # generic media/document descriptor nouns
        "map",
        "photo",
        "photograph",
        "photographs",
        "picture",
        "pictures",
        "image",
        "images",
        "diagram",
        "diagrams",
        "illustration",
        "painting",
        "drawing",
        "sketch",
        "poster",
        "postcard",
        "print",
        "engraving",
        "portrait",
        "view",
        "scene",
        "file",
        "jpg",
        "jpeg",
        "png",
        "gif",
        # generic industrial/wartime nouns that recur across thousands of
        # unrelated WWII-era archive titles
        "coal",
        "mine",
        "mines",
        "mining",
        "rail",
        "rails",
        "railway",
        "railroad",
        "railyard",
        "train",
        "trains",
        "tank",
        "tanks",
        "yard",
        "yards",
        "depot",
        "depots",
        "oil",
        "war",
        "army",
        "military",
        "navy",
        "factory",
        "factories",
        "plant",
        "plants",
        "industrial",
        "industry",
        "works",
        "wagon",
        "wagons",
        "hopper",
        "wreck",
        "ship",
        "ships",
        "shipping",
        "land",
        "landing",
        "class",
        "process",
        "processes",
    }
)

_DISTINCTIVE_WEIGHT = 1.0
_GENERIC_WEIGHT = 0.25

# How much of a candidate's `description` contributes to matching, verified
# against the real Wikimedia API (not the regression table - a live-check
# finding of its own): Commons' `ImageDescription` is sometimes a short,
# specific caption, but sometimes an auto-scraped multi-thousand-character
# Wikipedia biography, book excerpt, or museum catalog entry. Against the
# real API, a 22,000-character biography of the Portuguese writer Eça de
# Queirós happened to contain both "Germany" and "coalfields" somewhere in
# its text (a passing mention of Newcastle-area coalfields, a separate
# passing mention of Germany) and scored a perfect 1.0 for the query
# "Germany coalfields map" - a coincidence of text volume, not a real
# match, and a worse false positive than any generic-word collision in the
# regression table above. The real caption/subject is always at the front;
# capping how much text is indexed bounds the odds of a coincidental hit
# without losing genuine signal from focused descriptions (verified: this
# collapses that false positive, and two other real ones found the same
# way, to 0.0-0.2, while leaving the genuine Leuna/Sasol title matches
# untouched since those never depended on description length at all).
_DESCRIPTION_HEAD_CHARS = 300

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _normalise(text: str) -> str:
    # NFKD + drop combining marks strips diacritics (Ç -> C, ü -> u) so
    # "Bf Livraçao" and "Güssing" tokenise the same way an ASCII query does -
    # without this, a real match could be missed by an accent alone, and
    # (as observed) a diacritic-bearing foreign title never accidentally
    # collides with an English query either.
    decomposed = unicodedata.normalize("NFKD", text)
    without_marks = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return without_marks.lower().replace("_", " ")


def _content_tokens(text: str) -> list[str]:
    """Lowercased, diacritic-stripped, punctuation-split tokens with
    stopwords removed. Generic terms are kept (they still carry partial
    weight) - only true function words are dropped here."""
    return [tok for tok in _TOKEN_RE.findall(_normalise(text)) if tok not in _STOPWORDS]


def _term_weight(token: str) -> float:
    return _GENERIC_WEIGHT if token in _GENERIC_TERMS else _DISTINCTIVE_WEIGHT


def term_overlap_relevance(query_text: str, candidate_text: str) -> float:
    """Genuine term-overlap relevance in [0, 1] between a search query and a
    candidate's own text (title, description, or both joined). Pure and
    unit-testable - no network, no provider objects.

    The score is the fraction of the query's *weighted* content words that
    appear in the candidate text: distinctive (rare) words count fully,
    generic words (see `_GENERIC_TERMS`) count for a quarter. Matching one
    generic word ("South", "coal") is therefore never enough on its own;
    matching one distinctive word ("Leuna", "Sasol") is.
    """
    query_tokens = set(_content_tokens(query_text))
    if not query_tokens:
        return 0.0
    candidate_tokens = set(_content_tokens(candidate_text))

    total_weight = sum(_term_weight(tok) for tok in query_tokens)
    matched_weight = sum(_term_weight(tok) for tok in query_tokens if tok in candidate_tokens)
    return matched_weight / total_weight if total_weight else 0.0


def candidate_relevance(search_terms: list[str], candidate: AssetCandidate) -> float:
    """`term_overlap_relevance` adapted to the pipeline's actual shapes: the
    shot's list of search queries against the candidate's title plus its
    (often much richer, but see `_DESCRIPTION_HEAD_CHARS`) provider
    description - Wikimedia's `extmetadata` carries `ImageDescription`/
    `ObjectName`, Pexels supplies `alt`."""
    query_text = " ".join(search_terms)
    candidate_text = f"{candidate.title} {candidate.description[:_DESCRIPTION_HEAD_CHARS]}"
    return term_overlap_relevance(query_text, candidate_text)


def passes_relevance_gate(score: float) -> bool:
    """The hard gate itself (implementation guide, Phase M6 advice on the
    licence check applies equally here): a candidate scoring below
    `settings.asset_relevance_threshold` is discarded before it is ever
    downloaded or ranked, never merely deprioritised."""
    return score >= settings.asset_relevance_threshold
