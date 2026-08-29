"""Noise floor for the depiction gate: is a size flip resolution, or the model?

`output_quality_pass.md` §17.6 (RV-Q18). The §15.4 sweep ran ONE call
per (case, size) and read a single flip as a resolution effect. §14.7
had already established that this model needs a noise floor first. This
repeats the four A30a **keep** cases — the only ones the keep-bar turns
on — N times at full / 1024 / 512 and reports a reject *rate* per cell.

Reuses `_CASES` / `_find_asset` / `_one` from
`measure_depiction_downscale.py` so it hits exactly the same
`check_depiction` path, prompt and model, not a second one.

The load-bearing control: `ft_diagram_keep` is already ≤1024, so
`_downscale_for_focal` returns it untouched. The `full` and `1024` cells
therefore send byte-identical input — any disagreement between them is
the model, and cannot be resolution.

    ../.venv/Scripts/python.exe scripts/measure_depiction_noise.py
"""

from __future__ import annotations

import asyncio
import sys
from collections import defaultdict
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "scripts"))

from measure_depiction_downscale import _CASES, _find_asset, _mime, _one  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.providers.openai_provider import OpenAIPlanningProvider  # noqa: E402

REPEATS = 3
SIZES = (0, 1024, 512)  # 0 = full-res
WANT = {"ft_diagram_keep", "leuna_bundesarchiv_keep", "plant_58f0_keep", "sasol_ctl_keep"}


async def main() -> int:
    if not settings.openai_api_key:
        print("FAIL: settings.openai_api_key is empty — set OPENAI_API_KEY in .env")
        return 2

    provider = OpenAIPlanningProvider()
    cases = [case for case in _CASES if case.id in WANT]
    print(f"model={settings.openai_vision_model}  repeats={REPEATS}  cases={len(cases)}")
    print()

    tally: dict[tuple[str, str], list[bool]] = defaultdict(list)
    reasons: dict[tuple[str, str], list[str]] = defaultdict(list)

    for case in cases:
        path = _find_asset(case.content_hash)
        raw = path.read_bytes()
        ctype = _mime(path)
        print(f"== {case.id}  ({case.note})")
        for max_px in SIZES:
            label = "full" if max_px == 0 else str(max_px)
            for run in range(REPEATS):
                row = await _one(
                    provider, case=case, image=raw, content_type=ctype, max_px=max_px
                )
                tally[(case.id, label)].append(bool(row["confidently_wrong"]))
                reasons[(case.id, label)].append(str(row["reason"])[:70])
                print(
                    f"  {label:>4} run{run + 1}  wrong={row['confidently_wrong']!s:<5} "
                    f"tok={row['input_tokens']}  {str(row['reason'])[:60]!r}"
                )
                await asyncio.sleep(2.0)  # TPM cushion (200k/min on mini)
        print()

    print("REJECT RATE  (n rejected / n runs)")
    print(f"{'case':<28} {'full':>8} {'1024':>8} {'512':>8}")
    for case in cases:
        cells = [
            f"{sum(tally[(case.id, label)])}/{len(tally[(case.id, label)])}"
            for label in ("full", "1024", "512")
        ]
        print(f"{case.id:<28} {cells[0]:>8} {cells[1]:>8} {cells[2]:>8}")

    print()
    print("STABILITY: a cell that is not 0/N or N/N is the model, not the size.")
    for key, verdicts in tally.items():
        if 0 < sum(verdicts) < len(verdicts):
            print(f"  UNSTABLE {key[0]} @ {key[1]}: {sum(verdicts)}/{len(verdicts)}")
            for reason in reasons[key]:
                print(f"      {reason!r}")
    return 0


raise SystemExit(asyncio.run(main()))
