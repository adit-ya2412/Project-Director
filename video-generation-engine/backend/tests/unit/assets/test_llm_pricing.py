"""Pure unit tests for OQ-4.4 llm_call pricing (no DB, no network).

Must run under `pytest <path> --noconftest`.
"""

from app.assets.llm_pricing import attach_llm_call_pricing, llm_call_pricing


def test_exact_gpt_4o_mini():
    p = llm_call_pricing("gpt-4o-mini", 1_000_000, 1_000_000)
    assert p.input_usd_per_1m == 0.15
    assert p.output_usd_per_1m == 0.60
    # 0.15*100 + 0.60*100 = 75 cents
    assert p.cost_cents == 75


def test_snapshot_prefix_matches_gpt_4o_mini():
    p = llm_call_pricing("gpt-4o-mini-2024-07-18", 1_000_000, 0)
    assert p.input_usd_per_1m == 0.15
    assert p.output_usd_per_1m == 0.60
    assert p.cost_cents == 15


def test_gpt_5_5_rates():
    p = llm_call_pricing("gpt-5.5", 1_000_000, 1_000_000)
    assert p.input_usd_per_1m == 5.0
    assert p.output_usd_per_1m == 30.0
    assert p.cost_cents == 3500


def test_gpt_5_6_terra_rates():
    p = llm_call_pricing("gpt-5.6-terra", 1_000_000, 1_000_000)
    assert p.input_usd_per_1m == 2.0
    assert p.output_usd_per_1m == 12.0
    assert p.cost_cents == 1400


def test_unknown_model_is_none_not_zero():
    p = llm_call_pricing("fake-vision-model", 35035, 10)
    assert p.cost_cents is None
    assert p.input_usd_per_1m is None
    assert p.output_usd_per_1m is None


def test_known_model_missing_tokens_cost_zero_with_rates():
    p = llm_call_pricing("gpt-4o-mini", None, None)
    assert p.cost_cents == 0
    assert p.input_usd_per_1m == 0.15
    assert p.output_usd_per_1m == 0.60


def test_known_model_zero_tokens_cost_zero_with_rates():
    p = llm_call_pricing("gpt-5.5", 0, 0)
    assert p.cost_cents == 0
    assert p.input_usd_per_1m == 5.0
    assert p.output_usd_per_1m == 30.0


def test_real_sized_gpt_4o_mini_rounds_to_one_cent():
    # 35035/1e6 * 0.15 * 100 = 0.525525 → round to 1
    p = llm_call_pricing("gpt-4o-mini", 35035, 5)
    assert p.cost_cents == 1
    assert p.input_usd_per_1m == 0.15
    assert p.output_usd_per_1m == 0.60


def test_attach_stamps_pricing_on_request_copy():
    original = {"messages": [{"role": "user", "content": "hi"}]}
    request, pricing = attach_llm_call_pricing(
        model="gpt-4o-mini",
        input_tokens=1000,
        output_tokens=0,
        request=original,
    )
    assert "pricing" not in original
    assert request["pricing"] == {
        "input_usd_per_1m": 0.15,
        "output_usd_per_1m": 0.60,
    }
    assert pricing.cost_cents == 0  # 1000 tokens of mini is sub-cent, rounds to 0


def test_attach_unknown_model_stamps_null_rates():
    request, pricing = attach_llm_call_pricing(
        model="fake-vision-model",
        input_tokens=10,
        output_tokens=10,
        request={},
    )
    assert request["pricing"] == {
        "input_usd_per_1m": None,
        "output_usd_per_1m": None,
    }
    assert pricing.cost_cents is None
