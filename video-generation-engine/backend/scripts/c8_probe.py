"""C8 — timeline document growth, measured at real scale (docs/plans/
track_c_long_form_video.md §9, "Suggested scope"). §9's 232 KB figure at
185 shots was a linear extrapolation from the real 13-shot
`m8_test_project` fixture (16 KB, ~1,250 bytes/shot); §9 itself flags
that the per-shot constant may not hold, since `asset_plan.search_queries`
and `prompt`/`intent_text` are the bulk of a shot and their length is
free-text, not structural. This probe builds a 185-shot Timeline with
REALISTIC field content (sampled from real fixture shots, not the C0
probe's empty placeholders) and measures the real serialized size,
`find_additive_violations` diff cost, and `compute_render_fingerprint`
cost — the three consequences §9 names as "no longer free" at length.

No DB, no LLM call — pure in-memory Timeline construction + the real,
unmodified `Timeline.model_dump`, `find_additive_violations`, and
`compute_render_fingerprint`.

    docker compose run --rm backend python scripts/c8_probe.py
"""

import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))

from app.renderer.fingerprint import compute_render_fingerprint  # noqa: E402
from app.renderer.slideshow import RenderSettings  # noqa: E402
from app.timeline.additive import find_additive_violations  # noqa: E402
from app.schemas.timeline import (  # noqa: E402
    AssetPlan,
    AssetStrategy,
    Camera,
    CameraDirection,
    CameraMovement,
    Framing,
    PreferredMediaType,
    ProducedBy,
    Scene,
    Shot,
    ShotIntent,
    Timeline,
    TimelineStatus,
    Transition,
    TransitionType,
)

FIXTURE_PATH = _BACKEND / "tests" / "fixtures" / "m8_test_project.json"
N_SHOTS = 185
N_SCENES = 65


def _compact(obj) -> str:
    """Matches `compute_render_fingerprint`'s own serialisation
    (`json.dumps(..., sort_keys=True, separators=(",", ":"))`) — the
    byte count this probe reports is the one that actually lands on
    disk/in Postgres, not a pretty-printed approximation of it."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _real_shot_texts() -> tuple[list[str], list[str], list[list[str]]]:
    """Sample prompt/intent_text/search_queries from the real 13-shot
    fixture — free-text fields whose length a synthetic filler string
    cannot represent, which is exactly what §9 flagged as uncertain."""
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    shots = [s for scene in fixture["timeline_document"]["scenes"] for s in scene["shots"]]
    prompts = [s["prompt"] for s in shots]
    intent_texts = [s["intent_text"] for s in shots]
    queries = [s["asset_plan"]["search_queries"] for s in shots]
    return prompts, intent_texts, queries


def build_realistic_timeline() -> Timeline:
    prompts, intent_texts, queries = _real_shot_texts()
    intents = list(ShotIntent)
    framings = list(Framing)
    movements = list(CameraMovement)

    shots: list[Shot] = []
    for i in range(N_SHOTS):
        is_last = i == N_SHOTS - 1
        transition = (
            Transition(type=TransitionType.CUT, duration_s=0.0)
            if is_last or i % 5 == 4
            else Transition(type=TransitionType.DISSOLVE, duration_s=0.4)
        )
        shots.append(
            Shot(
                id=f"s{i:03d}",
                order=i,
                intent=intents[i % len(intents)],
                intent_text=intent_texts[i % len(intent_texts)],
                narration_span=(i * 60, i * 60 + 55),
                duration_s=3.2,
                framing=framings[i % len(framings)],
                camera=Camera(
                    movement=movements[i % len(movements)],
                    direction=CameraDirection.IN,
                    intensity=0.2,
                ),
                transition_out=transition,
                prompt=prompts[i % len(prompts)],
                asset_plan=AssetPlan(
                    entity=f"entity-{i % 7}",
                    strategy=AssetStrategy.PROJECT_ASSETS,
                    search_queries=queries[i % len(queries)],
                    preferred_type=PreferredMediaType.IMAGE,
                    fallback_chain=[
                        AssetStrategy.PROJECT_ASSETS,
                        AssetStrategy.HISTORICAL_SEARCH,
                        AssetStrategy.PUBLIC_DOMAIN,
                        AssetStrategy.STOCK_SEARCH,
                        AssetStrategy.GENERATE_IMAGE,
                    ],
                    licence_requirements=["public_domain", "cc0", "cc_by", "pexels_licence"],
                ),
            )
        )

    base, remainder = divmod(N_SHOTS, N_SCENES)
    scenes: list[Scene] = []
    idx = 0
    for scene_idx in range(N_SCENES):
        count = base + (1 if scene_idx < remainder else 0)
        scene_shots = shots[idx : idx + count]
        scenes.append(
            Scene(
                id=f"sc{scene_idx:03d}",
                order=scene_idx,
                title=f"Scene {scene_idx}",
                summary=f"A representative summary sentence for scene {scene_idx}, matching typical Director output length.",
                emotion="tense" if scene_idx % 2 else "hopeful",
                narrative_purpose="build stakes before the act turn" if scene_idx % 3 else "establish context",
                narration_text=" ".join(intent_texts[idx : idx + count]) or intent_texts[0],
                duration_s=sum(s.duration_s for s in scene_shots),
                shots=scene_shots,
            )
        )
        idx += count
    assert idx == N_SHOTS

    return Timeline(
        timeline_id="c8-probe",
        project_id="c8-probe-project",
        version=1,
        produced_by=ProducedBy.HUMAN,
        status=TimelineStatus.DRAFT,
        created_at=datetime.now(UTC),
        scenes=scenes,
    )


def real_13_shot_baseline_bytes() -> int:
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    return len(_compact(fixture["timeline_document"]))


def main() -> None:
    baseline_bytes = real_13_shot_baseline_bytes()
    print(f"real m8_test_project (13 shots), compact JSON: {baseline_bytes} bytes "
          f"({baseline_bytes / 13:.0f} bytes/shot)")

    timeline = build_realistic_timeline()
    document = timeline.model_dump(mode="json")
    raw = _compact(document)
    n_bytes = len(raw)
    print(f"\nsynthesised {N_SHOTS}-shot / {N_SCENES}-scene timeline, realistic content:")
    print(f"  {n_bytes} bytes ({n_bytes / N_SHOTS:.0f} bytes/shot)")
    print(f"  vs §9's linear extrapolation from 13 shots: {round(baseline_bytes / 13 * N_SHOTS)} bytes")
    print(f"  vs §9's stated 232 KB figure: {'confirmed' if abs(n_bytes - 232_000) < 40_000 else 'DIVERGES'}")

    # §9's append-growth arithmetic, with the real measured bytes/version
    # in place of the 232 KB extrapolation.
    for n_appends, label in [(7, "normal run, no human edits"), (57, "+ 50 per-shot overrides")]:
        total_mb = n_bytes * n_appends / 1024 / 1024
        print(f"  {label}: {n_appends} versions x {n_bytes} bytes = {total_mb:.2f} MB")

    # find_additive_violations: the cost of ONE scene approval's diff,
    # old vs new, at real 185-shot document size.
    old_doc = document
    new_doc = json.loads(json.dumps(document))  # deep copy
    new_doc["metadata"]["approved_scenes"] = ["sc000"]
    start = time.monotonic()
    violations = find_additive_violations(old_doc, new_doc, frozenset({"metadata.approved_scenes"}))
    diff_elapsed = time.monotonic() - start
    print(f"\nfind_additive_violations (185-shot doc, 1-field change): "
          f"{diff_elapsed * 1000:.2f}ms, {len(violations)} violations (expect 0)")

    # compute_render_fingerprint: real cost at 185 shots.
    render_settings = RenderSettings(width=720, height=1280, fps=30, pixel_format="yuv420p")
    start = time.monotonic()
    fingerprint = compute_render_fingerprint(
        timeline=timeline,
        asset_content_hashes=[f"hash{i:03d}" for i in range(N_SHOTS)],
        narration_content_hashes=[f"nhash{i:03d}" for i in range(N_SCENES)],
        music_content_hash="musichash",
        render_settings=render_settings,
        music_bed_gain_db=-18.0,
        music_duck_gain_db=-24.0,
        burn_captions=False,
        caption_font_hash=None,
        cue_list_hash=None,
        watermark_enabled=False,
        watermark_asset_hash=None,
        watermark_params_hash=None,
        burn_text_cards=False,
        text_card_font_hash=None,
        ffmpeg_version="7.1.5",
    )
    fingerprint_elapsed = time.monotonic() - start
    print(f"compute_render_fingerprint (185 shots): {fingerprint_elapsed * 1000:.2f}ms "
          f"-> {fingerprint[:16]}...")

    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "baseline_13_shot_bytes": baseline_bytes,
        "baseline_bytes_per_shot": baseline_bytes / 13,
        "n_shots": N_SHOTS,
        "n_scenes": N_SCENES,
        "synthesised_bytes": n_bytes,
        "synthesised_bytes_per_shot": n_bytes / N_SHOTS,
        "linear_extrapolation_bytes": round(baseline_bytes / 13 * N_SHOTS),
        "find_additive_violations_ms": diff_elapsed * 1000,
        "compute_render_fingerprint_ms": fingerprint_elapsed * 1000,
    }
    out = _BACKEND / "storage" / "_c0_probe" / "c8_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
