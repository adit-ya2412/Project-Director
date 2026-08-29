"""Per-call LLM cost from model id + token counts (OQ-4.4).

Sibling to `cost.py`, which is generation/narration budget estimation —
that module's docstring would lie if LLM token pricing lived there.
Rates come from `app.core.config.LLM_USD_PER_1M_TOKENS`. Unknown models
return `cost_cents=None` (never 0) so a missing price cannot look free.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.config import LLM_USD_PER_1M_TOKENS


@dataclass(frozen=True, slots=True)
class LlmCallPricing:
    """Cents charged for one call, plus the rates used to compute them.

    All three fields are None together when the model is unknown.
    Known model + missing/zero tokens → cost_cents=0 with rates set
    (distinguishable from unknown).
    """

    cost_cents: int | None
    input_usd_per_1m: float | None
    output_usd_per_1m: float | None


def _lookup_rates(model: str) -> tuple[float, float] | None:
    """Exact key, else longest matching prefix (dated snapshot ids)."""
    table = LLM_USD_PER_1M_TOKENS
    if model in table:
        return table[model]
    matches = [(key, rates) for key, rates in table.items() if model.startswith(key)]
    if not matches:
        return None
    matches.sort(key=lambda item: len(item[0]), reverse=True)
    return matches[0][1]


def llm_call_pricing(
    model: str,
    input_tokens: int | None,
    output_tokens: int | None,
) -> LlmCallPricing:
    """Price one LLM exchange. Unknown model → all Nones, never cost 0."""
    rates = _lookup_rates(model)
    if rates is None:
        return LlmCallPricing(
            cost_cents=None,
            input_usd_per_1m=None,
            output_usd_per_1m=None,
        )
    in_rate, out_rate = rates
    in_tok = 0 if input_tokens is None else input_tokens
    out_tok = 0 if output_tokens is None else output_tokens
    cost = round((in_tok / 1e6) * in_rate * 100 + (out_tok / 1e6) * out_rate * 100)
    return LlmCallPricing(
        cost_cents=cost,
        input_usd_per_1m=in_rate,
        output_usd_per_1m=out_rate,
    )


def attach_llm_call_pricing(
    *,
    model: str,
    input_tokens: int | None,
    output_tokens: int | None,
    request: dict,
) -> tuple[dict, LlmCallPricing]:
    """Copy `request`, stamp `request["pricing"]`, return (request, pricing)."""
    pricing = llm_call_pricing(model, input_tokens, output_tokens)
    priced_request = dict(request)
    priced_request["pricing"] = {
        "input_usd_per_1m": pricing.input_usd_per_1m,
        "output_usd_per_1m": pricing.output_usd_per_1m,
    }
    return priced_request, pricing
