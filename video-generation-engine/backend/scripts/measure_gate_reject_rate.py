"""READ-ONLY: where do assets actually get rejected, and does it matter?

`output_quality_pass.md` §18 (RV-Q22). Written to answer a plain
observation — "most of the assets are rejected on every project" — with
the verdicts already on disk instead of a guess about the model.

Three questions, in order:

1. **How often does the depiction gate reject?** Counted from
   `llm_call` rows where `agent='depiction_check'`. The verdict lives at
   `response["parsed"]["confidently_wrong"]`.
2. **Why?** Two very different failure modes hide inside one rate.
   *Wrong subject* ("a hard disk drive" for a coal gasifier) means the
   gate is right and the defect is upstream in search. *Right subject,
   wrong era* ("a modern laboratory") is A30a's false-reject class,
   where §17.7's run-to-run instability lives. Classified by reason
   language — a coarse split, deliberately: it is a signal about which
   half of the problem to chase, not a label set.
3. **Did the rejects cost anything?** A reject abandons that rung and
   the shot falls down the ladder (A30), so a high reject rate is
   compatible with every shot ending up filled. Resolved from the
   LATEST `timeline_version` per project, since `shot_binding` keeps
   every historical version.

SELECT only. No API calls, no writes. Safe to run against the shared
dev database while the server is up — but note `conftest.py`'s autouse
`clean_database` truncates that same database, so run this BEFORE any
pytest session, not after (§11).

    ../.venv/Scripts/python.exe scripts/measure_gate_reject_rate.py
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))

from sqlalchemy import text  # noqa: E402

from app.db.session import async_session_factory  # noqa: E402

# "right thing, wrong period" — the A30a false-reject class
_ERA = re.compile(r"\bmodern|contemporary|present-day|recent|today|21st|colou?r photo", re.I)
# "not the thing at all" — search handed the gate junk
_SUBJECT = re.compile(
    r"\brather than\b|\bnot related\b|\bunrelated\b|\bdoes not depict\b"
    r"|\bis not\b|\binstead of\b|\bno .{0,20}relation\b",
    re.I,
)


def _verdict(response) -> dict:
    """`response` is the raw chat completion; the parse sits under `parsed`."""
    doc = response if isinstance(response, dict) else json.loads(response)
    return doc.get("parsed") or doc


async def main() -> int:
    async with async_session_factory() as session:
        calls = (
            await session.execute(
                text(
                    "SELECT project_id, response FROM llm_call "
                    "WHERE agent = 'depiction_check'"
                )
            )
        ).all()
        outcomes = (
            await session.execute(
                text(
                    """
                    WITH latest AS (
                        SELECT project_id, max(timeline_version) AS v
                        FROM shot_binding GROUP BY project_id
                    )
                    SELECT b.project_id,
                           count(*) AS shots,
                           count(*) FILTER (WHERE b.state = 'resolved')  AS resolved,
                           count(*) FILTER (WHERE b.state = 'generated') AS generated,
                           count(*) FILTER (WHERE b.state NOT IN ('resolved', 'generated'))
                               AS unfilled
                    FROM shot_binding b
                    JOIN latest l ON l.project_id = b.project_id
                                 AND l.v = b.timeline_version
                    GROUP BY b.project_id
                    """
                )
            )
        ).all()

    if not calls:
        print("no depiction_check rows on record")
        return 1

    # --- 1. reject rate, per project ---
    per_project: dict[str, list[bool]] = defaultdict(list)
    for row in calls:
        per_project[str(row.project_id)].append(bool(_verdict(row.response).get("confidently_wrong")))

    total = sum(len(v) for v in per_project.values())
    rejected = sum(sum(v) for v in per_project.values())
    print(f"DEPICTION GATE: {rejected}/{total} rejected = {100 * rejected / total:.0f}%\n")

    # --- 2. why ---
    buckets: dict[str, int] = defaultdict(int)
    era_samples: list[str] = []
    for row in calls:
        verdict = _verdict(row.response)
        if not verdict.get("confidently_wrong"):
            continue
        reason = str(verdict.get("reason") or "")
        era, subject = bool(_ERA.search(reason)), bool(_SUBJECT.search(reason))
        buckets["both" if (era and subject) else "era" if era else "subject" if subject else "?"] += 1
        if era:
            era_samples.append(reason[:110])

    print("WHY (reason language)")
    for key, label in (
        ("subject", "wrong SUBJECT only   gate is right, search fed it junk"),
        ("era", "era/'modern' only    A30a false-reject risk"),
        ("both", "both                 mixed"),
        ("?", "unclassified"),
    ):
        n = buckets[key]
        print(f"  {n:>4}  {100 * n / rejected:>4.0f}%  {label}")

    print("\n  sample 'modern/contemporary' rejects:")
    for sample in era_samples[:10]:
        print(f"    - {sample}")

    # --- 3. did it cost anything ---
    print("\nWHAT SHOTS ACTUALLY ENDED UP WITH (latest timeline version)")
    print(f"{'project':<38} {'shots':>6} {'real':>5} {'gen':>4} {'none':>5} {'real%':>6} {'rej%':>6}")
    tot = [0, 0, 0, 0]
    for row in sorted(outcomes, key=lambda r: -r.shots):
        verdicts = per_project.get(str(row.project_id))
        rej = f"{100 * sum(verdicts) / len(verdicts):.0f}%" if verdicts else "-"
        tot = [
            tot[0] + row.shots,
            tot[1] + row.resolved,
            tot[2] + row.generated,
            tot[3] + row.unfilled,
        ]
        print(
            f"{str(row.project_id):<38} {row.shots:>6} {row.resolved:>5} {row.generated:>4} "
            f"{row.unfilled:>5} {100 * row.resolved / row.shots:>5.0f}% {rej:>6}"
        )
    print(
        f"{'TOTAL':<38} {tot[0]:>6} {tot[1]:>5} {tot[2]:>4} {tot[3]:>5} "
        f"{100 * tot[1] / tot[0]:>5.0f}%"
    )
    print(
        "\nA high gate reject rate is NOT the same as a starved project: a reject\n"
        "abandons that rung and the shot falls down the ladder (A30). Read the\n"
        "'gen' column, not the reject rate, for what the gate actually cost."
    )
    return 0


raise SystemExit(asyncio.run(main()))
