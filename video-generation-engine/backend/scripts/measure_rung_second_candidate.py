"""§18.5 / RV-Q22: when the gate rejects candidate #1, does #2 of the same pool pass?

A30 scoped the depiction check to the top-ranked candidate of a rung and
`resolve_assets.py` `break`s the candidate loop on `confidently_wrong`,
on the premise that a bad top means a bad pool. This script re-asks the
production gate about candidate #2 from frozen ranking pools that already
died on a reject.

Hits `OpenAIPlanningProvider.check_depiction` directly (same path as
`measure_depiction_downscale.py`) — never `check_candidate_plausibility`,
so nothing is written to `llm_call`. Does not change the `break`.

Frozen set: Wikimedia rungs from archival projects (Oil and War /
Radar WWII), written by `freeze_rvq22_wikimedia.py` into
`_rvq22_archival_cases.json`. Distinct candidate #1 source_ids are
checked before any vision call. Pexels `_CASES` below are the §18.5
first pass (superseded by §18.6).

§17.6: three draws per cell. Report rates. Flag any cell that is neither
0/N nor N/N.

    ../.venv/Scripts/python.exe scripts/measure_rung_second_candidate.py

DB was consulted once, SELECT-only, to build `_CASES` — before any pytest.
"""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import httpx

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))

from app.assets.validation import mime_type_for_extension, validate_and_identify_image  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.core.errors import PermanentError, TransientError  # noqa: E402
from app.providers.base import DepictionCheckRequest  # noqa: E402
from app.providers.openai_provider import OpenAIPlanningProvider  # noqa: E402

_RUNS = 3
_CACHE = Path(__file__).resolve().parent / "_rvq22_cache"
_ARCHIVAL_JSON = Path(__file__).resolve().parent / "_rvq22_archival_cases.json"
_PEXELS_PHOTO = "https://api.pexels.com/v1/photos/{id}"


@dataclass(frozen=True)
class Case:
    id: str
    source_id_1: str
    source_id_2: str
    n_pool: int
    shot_prompt: str
    search_subject: str
    historic_reason: str


# Frozen 2026-08-29 from 1cdf55ac ranking log + llm_call rejects + latest timeline.
# Unique shot_id, first ranking pool with ≥2 candidates.
_CASES: tuple[Case, ...] = (
    Case(
        "sc_02_sh_02",
        "11687350",
        "8153589",
        5,
        "small child hands tightening racing gloves beside a junior kart steering wheel, contemporary karting documentary, crisp realistic detail",
        "child racing gloves / junior kart steering wheel / karting driver hands / youth kart preparation",
        "shows only a steering wheel of a kart, lacking any visible han",
    ),
    Case(
        "sc_02_sh_05",
        "13245001",
        "5640638",
        3,
        "junior kart racing team garage with multiple race karts, stacks of new tires, transport cases and mechanics at work, high-cost professional karting operation, contemporary documentary photography",
        "junior karting team garage / karting paddock mechanics / race kart tire stacks / professional karting operation",
        "go-kart racing on a track rather than a junior kart racing team garage",
    ),
    Case(
        "sc_03_sh_02",
        "15397789",
        "29382707",
        3,
        "Formula 2 driver standing alone beside a race car in a crowded paddock, mechanics and equipment cases surrounding him, tense contemporary motorsport documentary mood",
        "Formula 2 paddock / F2 driver paddock / race team garage / single seater mechanics",
        "different kind of racing scene (likely a drift event)",
    ),
    Case(
        "sc_03_sh_03",
        "15397789",
        "16600134",
        3,
        "Close view of a junior single-seater team's race budget documents, calculator, invoices, and paddock credential on a worktable, contemporary motorsport documentary style",
        "motorsport budget documents / race team invoices / paddock credential / racing calculator",
        "does not depict financial documents... shows individuals working on a car",
    ),
    Case(
        "sc_05_sh_02",
        "160271901",
        "189045117",
        5,
        "young Lewis Hamilton in a modest late-1990s karting paddock, simple kart and practical family equipment, British circuit background, archival motorsport documentary style",
        "Lewis Hamilton karting / Lewis Hamilton 1997 / Hamilton kart paddock / British karting 1990s",
        "modern Formula 1 car... not the requested modest late-1990s karting paddock",
    ),
    Case(
        "sc_05_sh_03",
        "61205266",
        "61205326",
        5,
        "Anthony Hamilton in work clothes preparing equipment beside a small racing kart trailer, late-1990s Britain, family sacrifice, archival documentary photograph",
        "Anthony Hamilton karting / Anthony Hamilton 1990s / Hamilton kart trailer / British karting paddock",
        "close-up of a person, not ... Anthony Hamilton preparing equipment",
    ),
    Case(
        "sc_05_sh_06",
        "81130648",
        "110893196",
        5,
        "junior single-seater race start, young Lewis Hamilton's car accelerating ahead through a tightly packed Formula 3 grid, early-2000s European circuit, archival motorsport documentary style",
        "Lewis Hamilton Formula 3 / Hamilton F3 start / Formula 3 2004 grid / Formula 3 Euro Series",
        "modern Formula 1 car rather than a junior single-seater",
    ),
    Case(
        "sc_06_sh_05",
        "64263597",
        "64263594",
        5,
        "young racing driver wearing a modern Formula 1 race suit in a team garage, family member watching from behind the pit wall, contemporary motorsport documentary photography",
        "young F1 driver garage / Formula One race suit / F1 pit wall family / F1 driver paddock",
        "historical model (from around the early 2000s) rather than a contemporary driver",
    ),
    Case(
        "sc_06_sh_06",
        "155071018",
        "163385761",
        5,
        "Lance Stroll in Aston Martin Formula 1 race suit beside his green Formula 1 car in the paddock, contemporary editorial motorsport documentary photograph",
        "Lance Stroll Aston Martin / Lance Stroll paddock / Lance Stroll race suit / Aston Martin F1 Stroll",
        "moving Aston Martin Formula 1 car on track, not Lance Stroll beside his car",
    ),
    Case(
        "sc_07_sh_01",
        "64263652",
        "192000368",
        5,
        "Contemporary junior single-seater racing driver gripping the steering wheel in a helmeted cockpit, intense focused eyes, racetrack background, documentary motorsport photography, natural track light",
        "junior formula cockpit / single seater driver / helmeted racing driver / formula paddock driver",
        "vintage racing cars in a paddock setting",
    ),
    Case(
        "sc_07_sh_02",
        "57337417",
        "14457379",
        5,
        "Young karting driver attacking a corner at a competitive circuit, rain-specked visor and blurred curbing, late 1990s to 2000s karting documentary archive aesthetic",
        "kart racing rain / kart circuit corner / 1990s kart racing / junior kart driver",
        "parking lot with vehicles and a building in a modern setting",
    ),
    Case(
        "sc_07_sh_05",
        "64263652",
        "7357218",
        3,
        "Talented young driver sitting alone on a paddock bench beside the circuit while funded junior formula cars are prepared in the distance, contemporary motorsport documentary photography",
        "junior formula paddock / racing paddock bench / single seater preparation / formula race trailers",
        "vintage racing cars in a paddock... not contemporary... junior formula",
    ),
    Case(
        "sc_07_sh_06",
        "74055840",
        "18440296",
        5,
        "Formula 2 driver at full speed through a racetrack corner, tire spray and motion blur, vivid contemporary racing documentary imagery",
        "Formula 2 corner / F2 tire spray / Formula 2 racing / F2 wet race",
        "older Formula Renault or Formula Ford car, which differs from contemporary Formula 2",
    ),
)


def cell_kind(n_reject: int, n: int) -> str:
    """0/N pass, N/N reject, otherwise MIXED (coin-flip cell, §17.6)."""
    if n_reject == 0:
        return "pass"
    if n_reject == n:
        return "reject"
    return "MIXED"


async def _fetch_pexels_photo(photo_id: str) -> bytes:
    if not settings.pexels_api_key:
        raise PermanentError("PEXELS_API_KEY is not configured")
    _CACHE.mkdir(parents=True, exist_ok=True)
    cached = _CACHE / f"{photo_id}.jpg"
    if cached.is_file() and cached.stat().st_size > 0:
        return cached.read_bytes()
    headers = {"Authorization": settings.pexels_api_key}
    delay = 2.0
    last_exc: Exception | None = None
    for attempt in range(1, 6):
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                meta = await client.get(_PEXELS_PHOTO.format(id=photo_id), headers=headers)
                meta.raise_for_status()
                src = (meta.json().get("src") or {})
                url = src.get("original") or src.get("large") or ""
                if not url:
                    raise PermanentError(f"pexels photo {photo_id} has no src url")
                img = await client.get(url, follow_redirects=True)
                img.raise_for_status()
            cached.write_bytes(img.content)
            return img.content
        except (httpx.TimeoutException, httpx.TransportError, httpx.HTTPStatusError) as exc:
            last_exc = exc
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status in (401, 403, 404):
                raise PermanentError(f"pexels photo {photo_id} failed: {status}") from exc
            if attempt == 5:
                break
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30.0)
    raise TransientError(f"pexels photo {photo_id} fetch failed: {last_exc}")


def _load_archival_cases() -> list[Case]:
    if not _ARCHIVAL_JSON.is_file():
        return []
    raw = json.loads(_ARCHIVAL_JSON.read_text(encoding="utf-8"))
    return [
        Case(
            row["id"],
            str(row["source_id_1"]),
            str(row["source_id_2"]),
            int(row["n_pool"]),
            row["shot_prompt"],
            row["search_subject"],
            row["historic_reason"],
        )
        for row in raw
    ]


def _cache_bytes(source_id: str) -> bytes:
    path = _CACHE / f"wiki_{source_id}.bin"
    if not path.is_file():
        raise PermanentError(f"missing cache {path.name}")
    return path.read_bytes()


async def _ask(
    provider: OpenAIPlanningProvider,
    *,
    case: Case,
    image: bytes,
    content_type: str,
    rank: int,
    run: int,
) -> dict:
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
    return {
        "id": case.id,
        "rank": rank,
        "run": run,
        "confidently_wrong": bool(verdict.confidently_wrong),
        "reason": (verdict.reason or "").replace("\n", " ")[:140],
        "input_tokens": completion.input_tokens,
    }


async def main() -> int:
    if not settings.openai_api_key:
        print("FAIL: settings.openai_api_key is empty")
        return 2

    cases = _load_archival_cases()
    source = "wikimedia archival json"
    if not cases:
        cases = list(_CASES)
        source = "legacy pexels _CASES"

    ones = [c.source_id_1 for c in cases]
    if len(ones) != len(set(ones)):
        dup = sorted({i for i in ones if ones.count(i) > 1})
        print("FAIL: duplicate candidate #1 before any vision call:", dup)
        return 2

    print(f"model={settings.openai_vision_model}  depiction_image_max_px={settings.depiction_image_max_px}")
    print(f"source={source}  cases={len(cases)}  runs/cell={_RUNS}  distinct #1={len(set(ones))}")
    print()

    provider = OpenAIPlanningProvider()
    per_case: dict[str, dict[int, list[dict]]] = {}
    skipped: list[str] = []

    for case in cases:
        print(f"== {case.id}  pool={case.n_pool}  #{case.source_id_1} vs #{case.source_id_2}")
        print(f"   historic reject: {case.historic_reason}")
        try:
            if source.startswith("wikimedia"):
                img1, img2 = _cache_bytes(case.source_id_1), _cache_bytes(case.source_id_2)
            else:
                img1 = await _fetch_pexels_photo(case.source_id_1)
                img2 = await _fetch_pexels_photo(case.source_id_2)
            ext1, _, _ = validate_and_identify_image(img1)
            ext2, _, _ = validate_and_identify_image(img2)
            type1, type2 = mime_type_for_extension(ext1), mime_type_for_extension(ext2)
        except (PermanentError, TransientError) as exc:
            print(f"   SKIP fetch: {exc}")
            skipped.append(f"{case.id}: {exc}")
            continue
        per_case[case.id] = {1: [], 2: []}
        for rank, image, ctype in ((1, img1, type1), (2, img2, type2)):
            for run in range(1, _RUNS + 1):
                row = await _ask(
                    provider, case=case, image=image, content_type=ctype, rank=rank, run=run
                )
                per_case[case.id][rank].append(row)
                print(
                    f"   #{rank} run {run}/{_RUNS}  wrong={row['confidently_wrong']!s:<5}  "
                    f"tok={row['input_tokens']}  {row['reason'][:90]!r}"
                )
                await asyncio.sleep(1.5)
        print()

    print("RATES  (reject/runs)   MIXED = neither 0/N nor N/N")
    print(f"{'id':<28} {'#1':>6} {'#1 kind':<8} {'#2':>6} {'#2 kind':<8}  #2 pass given #1 reject?")
    n_stable_rej1 = 0
    n_stable_pass2_given = 0
    n_maj_pass2_given = 0
    n_mixed = 0
    for case in cases:
        cells = per_case.get(case.id)
        if cells is None:
            print(f"{case.id:<14} SKIP")
            continue
        r1 = sum(1 for row in cells[1] if row["confidently_wrong"])
        r2 = sum(1 for row in cells[2] if row["confidently_wrong"])
        k1, k2 = cell_kind(r1, _RUNS), cell_kind(r2, _RUNS)
        if k1 == "MIXED" or k2 == "MIXED":
            n_mixed += 1
        given = "-"
        if k1 == "reject":
            n_stable_rej1 += 1
            if k2 == "pass":
                n_stable_pass2_given += 1
                given = "YES (stable)"
            else:
                given = "no"
        if r1 >= 2 and r2 <= 1:
            n_maj_pass2_given += 1
            if given == "-":
                given = "majority-pass (#1 not 3/3)"
        print(f"{case.id:<28} {r1}/{_RUNS} {k1:<8} {r2}/{_RUNS} {k2:<8}  {given}")

    n_measured = len(per_case)
    print()
    print(f"measured rungs: {n_measured}/{len(cases)}  skipped={len(skipped)}")
    print(f"MIXED cells (either rank): {n_mixed} rungs")
    print(
        f"A30 test: among {n_stable_rej1} rungs where #1 is 3/3 reject, "
        f"#2 is 0/3 pass on {n_stable_pass2_given} "
        f"({(100 * n_stable_pass2_given / n_stable_rej1) if n_stable_rej1 else 0:.0f}%)"
    )
    print(
        f"looser: majority-pass on #2 while #1 is majority-reject: {n_maj_pass2_given} "
        f"(includes MIXED #1)"
    )
    if skipped:
        print("skipped:")
        for line in skipped:
            print(f"  {line}")

    if n_stable_rej1 == 0:
        print("DECISION: not enough stable #1 rejects to close A30; see log.")
    elif n_stable_pass2_given / n_stable_rej1 >= 0.25:
        print(
            "DECISION: #2 often passes — A30's 'bad top => bad pool' does NOT hold. "
            "Do not change the break in this task; ranking (or try-next-once) is a follow-up."
        )
    else:
        print(
            "DECISION: #2 rarely passes — A30 holds. Close §18.5; spend effort on search terms."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
