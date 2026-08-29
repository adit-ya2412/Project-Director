"""Measure whether downscaling re-opens the A30a depiction calibration.

§15.4 of output_quality_pass.md. Keep-bar (orchestrator, binding): for
each image, compare `confidently_wrong` at 512 / 1024 against full-res
on the SAME image, prompt, and model. Ship the largest size that holds
(0 extra false rejects AND 0 extra false accepts); if both flip, leave
production sending full-res.

Calls `OpenAIPlanningProvider.check_depiction` DIRECTLY — never
`check_candidate_plausibility` (no llm_call writes). 512/1024 images are
shrunk locally with `_downscale_for_focal` and passed as request bytes so
the measurement hits the gate, not a second code path.

    ../.venv/Scripts/python.exe scripts/measure_depiction_downscale.py
"""

from __future__ import annotations

import asyncio
import mimetypes
import sys
from dataclasses import dataclass
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
_ROOT = _BACKEND.parent
sys.path.insert(0, str(_BACKEND))

from app.assets.llm_pricing import llm_call_pricing  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.providers.base import DepictionCheckRequest  # noqa: E402
from app.providers.openai_provider import (  # noqa: E402
    OpenAIPlanningProvider,
    _downscale_for_focal,
)

_SIZES = (0, 1024, 512)  # 0 = full-res


@dataclass(frozen=True)
class Case:
    id: str
    content_hash: str
    shot_prompt: str
    search_subject: str
    note: str  # human context only; keep-bar ignores labels


# Frozen labeled set from on-disk assets. A30a load-bearing modes where
# files exist: wrong-country/region map, wrong structure type, modern vs
# archival, vs plausible industrial plant / process diagram. Greek map
# and motorcycle re-enactors from the original A30a table are NOT on
# disk anymore — not invented.
_CASES: tuple[Case, ...] = (
    Case(
        id="sasol_ctl_keep",
        content_hash="4363a4319390cdcda982d2b6bc684c8e3c6d1c28b8df3449b4fda68c72ee05e6",
        shot_prompt=(
            "1970–80 के दशक का दक्षिण अफ्रीकी सिंथेटिक-फ्यूल औद्योगिक संयंत्र, "
            "ऊंचे पाइप, धुआं छोड़ते टावर और कोयला-प्रसंस्करण संरचनाएं, "
            "श्वेत-श्याम अभिलेखीय औद्योगिक डॉक्यूमेंट्री शैली"
        ),
        search_subject="Sasol Secunda 1980; Sasolburg refinery 1975; Secunda coal gasification",
        note="plausible industrial plant (A30a keep)",
    ),
    Case(
        id="leuna_bundesarchiv_keep",
        content_hash="9ce6908743c427a0b69a4ebf12ec49eb61d08b4c36456c6558f7fc314a6f82e9",
        shot_prompt=(
            "1940s Nazi Germany coal-based synthetic fuel hydrogenation plant, "
            "coal conveyors feeding a vast industrial refinery, workers in "
            "protective clothing, smokestacks, monochrome archival industrial "
            "documentary photograph"
        ),
        search_subject="Leuna Werke 1943; Pölitz hydrogenation plant; German synthetic fuel",
        note="Bundesarchiv Leuna — A30a false-reject regression case (keep)",
    ),
    Case(
        id="ft_diagram_keep",
        content_hash="d984ffb1080af91ca5e9a1cab549e7634507df34ddbe14e5a6c30d257c4eec6e",
        shot_prompt=(
            "simple unlabeled archival-era chemical process diagram showing coal "
            "entering an industrial conversion vessel and emerging as liquid fuel, "
            "black-and-white technical documentary aesthetic, aged paper texture"
        ),
        search_subject="Fischer Tropsch diagram; Bergius process diagram; coal hydrogenation diagram",
        note="FT process diagram — A30a false-reject regression case (keep)",
    ),
    Case(
        id="plant_58f0_keep",
        content_hash="c76ad98f605bc9e8cd51b238e790b9db6e49e82581dbf9fc9e714143ea856ccf",
        shot_prompt=(
            "mid-century coal-to-liquids refinery, dark coal entering industrial "
            "processing equipment beside clear liquid fuel flowing into a "
            "collection vessel, German synthetic-fuel industry aesthetic, archival "
            "industrial documentary photograph, restrained factory atmosphere"
        ),
        search_subject="German synthetic fuel plant; Fischer Tropsch plant; Leuna Werke refinery",
        note="plausible industrial plant still from 58f0a5e6",
    ),
    Case(
        id="crucifixion_vs_oil_map",
        content_hash="cfc72372b7cc7ee8e9f782df2a47c363416b1a88d4dacd96274091ab85988d3a",
        shot_prompt=(
            "द्वितीय विश्व युद्धकालीन नाज़ी जर्मनी का श्वेत-श्याम संसाधन मानचित्र, "
            "जर्मनी पर केंद्रित, पेट्रोलियम स्रोतों की कमी दर्शाता विरल औद्योगिक "
            "मानचित्रण, अभिलेखीय औद्योगिक डॉक्यूमेंट्री शैली"
        ),
        search_subject="Germany oil map 1942; Nazi Germany resources map; German petroleum map",
        note="wrong subject type (painting vs map) — A30a reject",
    ),
    Case(
        id="south_america_vs_sa_embargo",
        content_hash="37f3bbe283b4cb05ea2353ff053c230037ca8d833cde07126c00777f7be0998e",
        shot_prompt=(
            "1970–80 के दशक का दक्षिणी अफ्रीका का अभिलेखीय नक्शा, तेल आपूर्ति "
            "मार्गों से अलग-थलग दक्षिण अफ्रीका, पास में तेल-प्रतिबंध संदर्भ वाला "
            "पुराना समाचारपत्र, संयमित श्वेत-श्याम डॉक्यूमेंट्री शैली"
        ),
        search_subject="South Africa oil embargo; apartheid oil sanctions; South Africa 1980 map",
        note="wrong-country map (South America for South Africa) — A30a reject",
    ),
    Case(
        id="ships_vs_oil_depot",
        content_hash="c97e34d75726cad21240f62bbb414b815a247ca6b1a26aa31a124494cdcf2166",
        shot_prompt=(
            "1940 German oil depot / fuel storage yard, archival industrial "
            "documentary photograph, monochrome"
        ),
        search_subject="German oil depot 1940; WWII fuel storage Germany",
        note="wrong structure type (ships painting) — A30a reject",
    ),
    Case(
        id="polish_elevator_vs_leuna",
        content_hash="e7c8c93a98b900918659ea6ccf0fb3f5360cea6c2bf06010ac2e6b527878a895",
        shot_prompt=(
            "Leuna-Werke synthetic-fuel factory during the Second World War, "
            "towering distillation columns, smoke drifting from chimneys, "
            "workers and rail tank wagons operating through the night, sober "
            "archival industrial documentary photograph, monochrome"
        ),
        search_subject="Leuna Werke 1943; Leuna synthetic fuel; Leuna hydrogenation plant",
        note="wrong structure type (derelict Polish coal elevator) — A30a reject",
    ),
    Case(
        id="gorki_map_vs_germany_coalfields",
        content_hash="73eabb13c51145691282a0d9fea55f6ba4055212c63f1cd749e08592926e1c48",
        shot_prompt=(
            "द्वितीय विश्व युद्ध काल का श्वेत-श्याम औद्योगिक डॉक्यूमेंट्री दृश्य, "
            "यूरोप का युद्धकालीन संसाधन मानचित्र, जर्मनी पर केंद्रित भूभाग, कोयला "
            "क्षेत्रों और रेल संपर्कों का सूक्ष्म दृश्य संकेत, गंभीर अभिलेखीय बनावट"
        ),
        search_subject="Germany coalfields map; German railway map 1940; WWII Europe resource map",
        note="wrong-region map (Gorki recon) for Germany coalfields — A30a reject",
    ),
    Case(
        id="montparnasse_vs_resource_map",
        content_hash="389e92b52917346c01dde56b57f9fc0f3001fda48a4851de57fcfaf49726009c",
        shot_prompt=(
            "द्वितीय विश्व युद्ध काल का श्वेत-श्याम औद्योगिक डॉक्यूमेंट्री दृश्य, "
            "यूरोप का युद्धकालीन संसाधन मानचित्र, जर्मनी पर केंद्रित भूभाग"
        ),
        search_subject="Germany coalfields map; WWII Europe resource map",
        note="wrong subject type (train wreck photo vs resource map)",
    ),
    Case(
        id="modern_holzvergaser_vs_archival",
        content_hash="47bd6f6ab93aafb69eb5bca0f92427060452f8e72e5170baa05fa929898b81c7",
        shot_prompt=(
            "1940s Nazi Germany coal-based synthetic fuel hydrogenation plant, "
            "smokestacks, monochrome archival industrial documentary photograph"
        ),
        search_subject="Leuna Werke 1943; German synthetic fuel",
        note="modern colour apparatus vs archival plant — era mismatch",
    ),
)


def _find_asset(content_hash: str) -> Path:
    """Prefer the plan's named project dirs, then any storage hit."""
    preferred = [
        _ROOT / "storage" / "58f0a5e6-008d-468e-862a-e365e463878e" / "assets",
        _ROOT / "storage" / "35290b04-584d-415e-9816-ab6a8998b3e2" / "assets",
        _ROOT / "backend" / "tests" / "fixtures" / "hinglish_final_project_media" / "assets",
    ]
    for folder in preferred:
        for ext in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
            candidate = folder / f"{content_hash}{ext}"
            if candidate.is_file():
                return candidate
    matches = list((_ROOT / "storage").rglob(f"{content_hash}.*"))
    matches = [p for p in matches if p.is_file()]
    if not matches:
        raise FileNotFoundError(f"no on-disk asset for {content_hash}")
    return matches[0]


def _mime(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(path.name)
    return guessed or "image/jpeg"


async def _one(
    provider: OpenAIPlanningProvider,
    *,
    case: Case,
    image: bytes,
    content_type: str,
    max_px: int,
) -> dict:
    from app.core.errors import TransientError

    if max_px > 0:
        image, content_type = _downscale_for_focal(image, content_type, max_px)

    delay = 2.0
    completion = None
    for attempt in range(1, 8):
        try:
            completion = await provider.check_depiction(
                DepictionCheckRequest(
                    image=image,
                    image_content_type=content_type,
                    shot_prompt=case.shot_prompt,
                    search_subject=case.search_subject,
                )
            )
            break
        except TransientError as exc:
            if attempt == 7:
                raise
            print(f"    retry {attempt}/6 after transient: {exc}"[:160])
            await asyncio.sleep(delay)
            delay = min(delay * 2, 60.0)
    assert completion is not None
    verdict = completion.parsed
    assert verdict is not None
    pricing = llm_call_pricing(
        completion.model or settings.openai_vision_model,
        completion.input_tokens,
        completion.output_tokens,
    )
    return {
        "id": case.id,
        "max_px": max_px or "full",
        "confidently_wrong": verdict.confidently_wrong,
        "reason": (verdict.reason or "").replace("\n", " ")[:120],
        "input_tokens": completion.input_tokens,
        "output_tokens": completion.output_tokens,
        "cost_cents": pricing.cost_cents,
        "model": completion.model,
    }


async def main() -> int:
    if not settings.openai_api_key:
        print("FAIL: settings.openai_api_key is empty — set OPENAI_API_KEY in .env")
        return 2

    print(f"model={settings.openai_vision_model}")
    print("NOTE: Greek topographic map + motorcycle re-enactors from A30a are not on disk.")
    print()

    provider = OpenAIPlanningProvider()
    rows: list[dict] = []
    by_case: dict[str, dict[str | int, dict]] = {}

    for case in _CASES:
        path = _find_asset(case.content_hash)
        raw = path.read_bytes()
        ctype = _mime(path)
        print(f"== {case.id}  {path.name[:16]}…  ({case.note})")
        case_rows: dict[str | int, dict] = {}
        for max_px in _SIZES:
            row = await _one(
                provider,
                case=case,
                image=raw,
                content_type=ctype,
                max_px=max_px,
            )
            rows.append(row)
            case_rows[max_px or "full"] = row
            print(
                f"  max_px={row['max_px']!s:>4}  wrong={row['confidently_wrong']!s:<5}  "
                f"tok_in={row['input_tokens']}  cost_cents={row['cost_cents']}  "
                f"reason={row['reason']!r}"
            )
            await asyncio.sleep(2.0)  # TPM cushion (200k/min on mini)
        by_case[case.id] = case_rows
        print()

    # Rejection table
    print("REJECTION TABLE")
    print(f"{'id':<36} {'max_px':>6} {'wrong':>5} {'tok_in':>7} {'¢':>3}  reason")
    for row in rows:
        print(
            f"{row['id']:<36} {str(row['max_px']):>6} {str(row['confidently_wrong']):>5} "
            f"{row['input_tokens'] or 0:>7} {row['cost_cents'] if row['cost_cents'] is not None else '-':>3}  "
            f"{row['reason']}"
        )

    def _hold(size: int) -> tuple[bool, list[str]]:
        flips: list[str] = []
        for case_id, sizes in by_case.items():
            full = sizes["full"]["confidently_wrong"]
            scaled = sizes[size]["confidently_wrong"]
            if full is False and scaled is True:
                flips.append(f"{case_id}: extra false reject (full False → {size} True)")
            elif full is True and scaled is False:
                flips.append(f"{case_id}: extra false accept (full True → {size} False)")
        return (not flips), flips

    print()
    hold_512, flips_512 = _hold(512)
    hold_1024, flips_1024 = _hold(1024)
    print(f"KEEP-BAR 512:  {'HOLD' if hold_512 else 'FAIL'}")
    for line in flips_512:
        print(f"  - {line}")
    print(f"KEEP-BAR 1024: {'HOLD' if hold_1024 else 'FAIL'}")
    for line in flips_1024:
        print(f"  - {line}")

    def _avg_tokens(size_key: str | int) -> float:
        vals = [
            sizes[size_key]["input_tokens"] or 0
            for sizes in by_case.values()
        ]
        return sum(vals) / len(vals) if vals else 0.0

    def _sum_cents(size_key: str | int) -> int:
        return sum(
            (sizes[size_key]["cost_cents"] or 0) for sizes in by_case.values()
        )

    print()
    print(
        f"avg input_tokens  full={_avg_tokens('full'):.0f}  "
        f"1024={_avg_tokens(1024):.0f}  512={_avg_tokens(512):.0f}"
    )
    print(
        f"sum cost_cents    full={_sum_cents('full')}  "
        f"1024={_sum_cents(1024)}  512={_sum_cents(512)}"
    )

    if hold_512:
        print("DECISION: ship depiction_image_max_px=512")
    elif hold_1024:
        print("DECISION: ship depiction_image_max_px=1024 (512 failed)")
    else:
        print("DECISION: do NOT wire production check_depiction downscale")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
