"""Freeze ~12 Wikimedia rungs for §18.5 re-measurement (RV-Q23).

SELECT-only against Postgres, then live Commons search+rank+fetch.
No vision calls. No llm_call writes. Writes
`scripts/_rvq22_archival_cases.json` for measure_rung_second_candidate.py.

Projects: archival (Radar WWII / Oil and War), not 1cdf55ac motorsport.
Distinct candidate #1 source_ids required.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))

from sqlalchemy import text  # noqa: E402

from app.assets.ranking import rank_candidates  # noqa: E402
from app.assets.relevance import candidate_relevance, passes_relevance_gate  # noqa: E402
from app.assets.validation import validate_and_identify_image  # noqa: E402
from app.core.errors import PermanentError, TransientError  # noqa: E402
from app.db.session import async_session_factory  # noqa: E402
from app.providers.base import AssetQuery  # noqa: E402
from app.providers.wikimedia import WikimediaAssetProvider  # noqa: E402

_OUT = Path(__file__).resolve().parent / "_rvq22_archival_cases.json"
_CACHE = Path(__file__).resolve().parent / "_rvq22_cache"
_FETCH_CAP = 5
_TARGET = 12
_PROJECT_PREFIXES = (
    "3d56cf87",  # Radar and worlwar2
    "6b790c76",  # Radar and WW2 (camera-vocab)
    "b6a2ae69",  # Oil and War
)
_DEFAULT_LICENCES = frozenset({"public_domain", "cc0", "cc_by"})


def _verdict(response) -> dict:
    doc = response if isinstance(response, dict) else json.loads(response)
    return doc.get("parsed") or doc


async def _load_reject_shots() -> list[dict]:
    async with async_session_factory() as s:
        projects = (await s.execute(text("SELECT id, name FROM project"))).mappings().all()
        wanted = []
        for p in projects:
            pid = str(p["id"])
            if any(pid.startswith(pref) for pref in _PROJECT_PREFIXES):
                wanted.append((pid, p["name"]))
        print("projects", wanted)
        shots: list[dict] = []
        seen_prompts: set[str] = set()
        for pid, name in wanted:
            rejs = (
                await s.execute(
                    text(
                        "SELECT request, response FROM llm_call "
                        "WHERE agent = 'depiction_check' "
                        "AND project_id = CAST(:pid AS uuid)"
                    ),
                    {"pid": pid},
                )
            ).mappings().all()
            reject_prompts: list[tuple[str, str, str]] = []
            for r in rejs:
                parsed = _verdict(r["response"])
                if not parsed.get("confidently_wrong"):
                    continue
                req = r["request"] if isinstance(r["request"], dict) else json.loads(r["request"])
                reject_prompts.append(
                    (
                        req.get("shot_prompt") or "",
                        req.get("search_subject") or "",
                        (parsed.get("reason") or "")[:160],
                    )
                )
            tl = (
                await s.execute(
                    text(
                        "SELECT document FROM timeline_version "
                        "WHERE project_id = CAST(:pid AS uuid) "
                        "ORDER BY version DESC LIMIT 1"
                    ),
                    {"pid": pid},
                )
            ).mappings().first()
            if tl is None:
                continue
            doc = tl["document"]
            period = (doc.get("metadata") or {}).get("historical_period") or ""
            for scene in doc.get("scenes") or []:
                for shot in scene.get("shots") or []:
                    prompt = shot.get("prompt") or ""
                    if prompt in seen_prompts:
                        continue
                    hit = next((x for x in reject_prompts if prompt[:80] == x[0][:80]), None)
                    if hit is None:
                        continue
                    seen_prompts.add(prompt)
                    plan = shot.get("asset_plan") or {}
                    shots.append(
                        {
                            "project_id": pid,
                            "project_name": name,
                            "shot_id": shot.get("id"),
                            "shot_prompt": prompt,
                            "search_queries": plan.get("search_queries") or [],
                            "licence_requirements": plan.get("licence_requirements") or [],
                            "historical_period": period,
                            "historic_reason": hit[2],
                            "search_subject": hit[1]
                            or " / ".join(plan.get("search_queries") or []),
                        }
                    )
        print(f"reject shots matched to timeline: {len(shots)}")
        return shots


async def _pool_for_shot(provider: WikimediaAssetProvider, shot: dict) -> dict | None:
    queries = shot["search_queries"] or [shot["shot_id"]]
    licences = set(shot["licence_requirements"]) or _DEFAULT_LICENCES
    query = AssetQuery(
        search_terms=queries,
        preferred_type="image",
        shot_id=shot["shot_id"],
        historical_period=shot["historical_period"],
    )
    try:
        candidates = await provider.search(query)
    except (PermanentError, TransientError) as exc:
        print(f"  search fail {shot['shot_id']}: {exc}")
        return None
    eligible = [c for c in candidates if c.licence in licences]
    relevant = [
        c for c in eligible if passes_relevance_gate(candidate_relevance(queries, c))
    ]
    if len(relevant) < 2:
        print(
            f"  {shot['shot_id']}: search={len(candidates)} lic={len(eligible)} "
            f"rel={len(relevant)} (<2)"
        )
        return None
    fetched = []
    for cand in relevant[:_FETCH_CAP]:
        try:
            got = await provider.fetch(cand)
            validate_and_identify_image(got.content)
        except (PermanentError, TransientError):
            continue
        content_hash = hashlib.sha256(got.content).hexdigest()
        fetched.append((cand, content_hash, got.content))
    if len(fetched) < 2:
        print(f"  {shot['shot_id']}: fetched {len(fetched)}")
        return None
    ranked = rank_candidates(
        [(c, h) for c, h, _ in fetched],
        search_terms=queries,
        historical_period=shot["historical_period"],
        shot_id=shot["shot_id"],
    )
    by_hash = {h: (c, blob) for c, h, blob in fetched}
    top = [by_hash[r.content_hash] for r in ranked[:2]]
    c1, b1 = top[0]
    c2, b2 = top[1]
    if c1.source_id == c2.source_id:
        return None
    _CACHE.mkdir(parents=True, exist_ok=True)
    p1 = _CACHE / f"wiki_{c1.source_id}.bin"
    p2 = _CACHE / f"wiki_{c2.source_id}.bin"
    p1.write_bytes(b1)
    p2.write_bytes(b2)
    return {
        "id": f"{shot['project_id'][:8]}_{shot['shot_id']}",
        "project_id": shot["project_id"],
        "project_name": shot["project_name"],
        "shot_id": shot["shot_id"],
        "source_id_1": c1.source_id,
        "source_id_2": c2.source_id,
        "title_1": c1.title,
        "title_2": c2.title,
        "url_1": c1.source_url,
        "url_2": c2.source_url,
        "n_pool": len(fetched),
        "shot_prompt": shot["shot_prompt"],
        "search_subject": shot["search_subject"],
        "historic_reason": shot["historic_reason"],
        "cache_1": p1.name,
        "cache_2": p2.name,
    }


async def main() -> int:
    shots = await _load_reject_shots()
    provider = WikimediaAssetProvider(rung="historical_search")
    cases: list[dict] = []
    seen_ones: set[str] = set()
    for shot in shots:
        if len(cases) >= _TARGET:
            break
        print(f"== {shot['project_name'][:22]} {shot['shot_id']}")
        pooled = await _pool_for_shot(provider, shot)
        if pooled is None:
            continue
        if pooled["source_id_1"] in seen_ones:
            print(f"  skip duplicate #1 {pooled['source_id_1']}")
            continue
        seen_ones.add(pooled["source_id_1"])
        cases.append(pooled)
        print(
            f"  KEEP n={pooled['n_pool']} #1={pooled['source_id_1']} "
            f"{pooled['title_1'][:50]!r} #2={pooled['source_id_2']} "
            f"{pooled['title_2'][:50]!r}"
        )
    print(f"\nfrozen {len(cases)} rungs; distinct #1={len(seen_ones)}")
    if len(seen_ones) != len(cases):
        print("FAIL: duplicate #1 slipped through")
        return 2
    _OUT.write_text(json.dumps(cases, ensure_ascii=False, indent=2), encoding="utf-8")
    print("wrote", _OUT)
    if len(cases) < 10:
        print("WARN: fewer than 10 rungs")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
