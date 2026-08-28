"""API-facing output schema for the caption romanizer.

See app/planners/director/schemas.py for why every field is required and
default-free (OpenAI structured-output strict mode).

caption_romanization.md §11: the model does plain 1:1 transliteration
only — one Devanagari-narration word in, one Latin display word out,
same order, nothing merged, nothing dropped. `§10`'s per-token `covers`
contract has been withdrawn: §10 let the LLM decide when several Hindi
number words merge into one digit token, and that produced two live
defects (over-merging bare digits like `90`, and once silently
producing the wrong numeral, `2006` instead of `2026`, while passing
every structural check). Numeral merging is now a deterministic code
pass over this plain output — see
`app/planners/caption_romanizer/numerals.py` — never an LLM decision.
"""

from pydantic import BaseModel


class CaptionRomanizerOutput(BaseModel):
    # The full scene, transliterated word-for-word into Latin script.
    # Same number of whitespace-delimited words as `narration_text`, same
    # order — enforced by `app/planners/caption_romanizer/planner.py::
    # romanization_violations`. Never trust the prompt alone (§2.2).
    caption_text: str
