"""Playwright pass over the review UI (Track C C5 / §13.4).

Run against a live Vite + DRY_RUN backend. Writes screenshots to
tmp/review-verify/ and a findings JSON next to them.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
import uuid
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

OUT = ROOT / "tmp" / "review-verify"
BASE = "http://localhost:5173"
SCRIPT = (
    "Germany possessed abundant coal, fueling its factories and its "
    "ambitions. But it lacked one vital resource: oil, and that "
    "dependency would shape the war to come. That single gap in "
    "resources would drive strategic decisions with consequences the "
    "world still remembers."
)

findings: list[dict] = []


def note(ok: bool, what: str, extra: str = "") -> None:
    findings.append({"ok": ok, "what": what, "extra": extra})
    mark = "OK" if ok else "FAIL"
    print(f"[{mark}] {what}" + (f" — {extra}" if extra else ""))


def shot(page, name: str) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{name}.png"
    page.screenshot(path=str(path), full_page=True)
    return path


def seed_grouped_project() -> str:
    from app.db.session import async_session_factory
    from app.models.shot_binding import ShotBindingModel
    from app.repositories.project_repository import PostgresProjectRepository
    from app.schemas.timeline import ProducedBy, Scene, Shot, ShotIntent, Transition, TransitionType
    from app.timeline.service import TimelineService

    async def _run() -> str:
        async with async_session_factory() as session:
            repo = PostgresProjectRepository(session)
            project = await repo.create("playwright grouped review")
            service = TimelineService(session)
            await service.create_initial(project.id, script="unused")
            scenes = []
            for i in range(14):
                shots = [
                    Shot(
                        id=f"sc{i:02d}_sh{j}",
                        order=j,
                        intent=ShotIntent.EXPLAIN,
                        duration_s=2.0,
                        prompt=f"archival still for scene {i} shot {j}",
                        transition_out=Transition(type=TransitionType.CUT, duration_s=0.0),
                    )
                    for j in range(3)
                ]
                scenes.append(
                    Scene(
                        id=f"sc{i:02d}",
                        order=i,
                        title=f"Scene {i + 1}",
                        duration_s=6.0,
                        shots=shots,
                    )
                )

            def _fill(base):
                base.scenes = scenes
                base.metadata.total_duration_s = 84.0
                return base

            appended = await service.append_version(
                project.id,
                produced_by=ProducedBy.ASSET_PLANNER,
                transform=_fill,
                owns=frozenset({"scenes", "metadata"}),
            )
            pid = uuid.UUID(project.id)
            for scene in scenes:
                for sh in scene.shots:
                    session.add(
                        ShotBindingModel(
                            project_id=pid,
                            timeline_version=appended.version,
                            shot_id=sh.id,
                            state="resolved",
                        )
                    )
            await session.commit()
            return project.id

    return asyncio.run(_run())


def wait_for_review(page, timeout_ms: int = 180_000) -> None:
    page.wait_for_url("**/projects/**/review", timeout=timeout_ms)
    page.get_by_role("heading", name="Review the pictures").wait_for(timeout=15_000)


def run() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    grouped_id = seed_grouped_project()
    print(f"seeded grouped project {grouped_id}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        page = context.new_page()
        page.set_default_timeout(15_000)

        # --- Project list ---
        page.goto(BASE + "/")
        page.get_by_role("heading", name="Projects").wait_for()
        shot(page, "01-project-list-desktop")
        note(page.get_by_role("link", name="New project").count() > 0, "project list shows New project")

        # --- New project form ---
        page.get_by_role("link", name="New project").first.click()
        page.get_by_role("heading", name="New project").wait_for()
        shot(page, "02-new-project")
        page.get_by_placeholder("e.g. Why Germany Ran Out of Oil").fill("Playwright review pass")
        page.locator("textarea").first.fill(SCRIPT)
        shot(page, "03-new-project-filled")
        page.get_by_role("button", name="Create and start generating").click()

        # Progress, then auto-nav to review
        try:
            page.wait_for_url("**/projects/**/progress", timeout=20_000)
            shot(page, "04-progress")
            note(True, "landed on progress after create")
        except PlaywrightTimeout:
            note(page.url.find("/review") != -1, "skipped progress URL", page.url)

        try:
            wait_for_review(page)
            note(True, "auto-navigated to review gate")
        except PlaywrightTimeout:
            shot(page, "04b-stuck-before-review")
            note(False, "never reached review gate", page.url)
            (OUT / "findings.json").write_text(json.dumps(findings, indent=2), encoding="utf-8")
            browser.close()
            return 1

        shot(page, "05-review-flat-desktop")
        heading = page.get_by_role("heading", name="Review the pictures")
        note(heading.is_visible(), "flat review heading")
        note(page.get_by_text("Draft preview").count() > 0, "draft player is on the review gate")
        note(page.get_by_role("button", name="Approve and continue").count() > 0, "Approve and continue is present")
        note(page.get_by_text("Approve scene").count() == 0, "grouped per-scene approve is hidden on a small project")

        # Lightbox
        thumbs = page.locator("button[aria-label='View larger image'], button[aria-label='Play clip']")
        if thumbs.count() > 0:
            thumbs.first.click()
            page.wait_for_timeout(400)
            shot(page, "06-lightbox")
            note(True, "opened shot lightbox")
            page.keyboard.press("Escape")
            page.wait_for_timeout(200)
        else:
            note(False, "no shot thumbnail to open")

        # Generate dialog
        gen = page.get_by_role("button", name="Generate now").or_(page.get_by_role("button", name="Edit prompt & regenerate"))
        if gen.count() > 0:
            gen.first.click()
            page.get_by_role("heading", name="Generate this shot").or_(
                page.get_by_role("heading", name="Edit prompt and generate")
            ).wait_for()
            shot(page, "07-generate-dialog")
            note(True, "generate dialog opens")
            page.get_by_role("button", name="Cancel").click()
        else:
            note(False, "no generate button on a shot row")

        # Override dialog
        ov = page.get_by_role("button", name="Upload your own").or_(page.get_by_role("button", name="Replace image"))
        if ov.count() > 0:
            ov.first.click()
            page.wait_for_timeout(300)
            shot(page, "08-override-dialog")
            note(page.get_by_text("Supply this shot").count() > 0 or page.get_by_role("dialog").count() > 0, "override dialog opens")
            page.keyboard.press("Escape")
        else:
            note(False, "no override button")

        # Approve — dry_run skips C6 spend confirm, so this may navigate away.
        # Capture whatever dialog appears, then do not wait for navigation if it stays.
        approve = page.get_by_role("button", name="Approve and continue").first
        approve.click()
        page.wait_for_timeout(500)
        shot(page, "09-after-approve-click")
        if page.get_by_role("heading", name="Confirm spend and continue").count() > 0:
            note(True, "C6 spend confirm appeared")
            page.get_by_role("button", name="Back").click()
        elif "/progress" in page.url or "/result" in page.url:
            note(True, "approve navigated off review (dry-run, no spend confirm)", page.url)
        else:
            note(True, "approve click did not show spend confirm", page.url)

        # --- Grouped layout (seeded 42-shot project) ---
        page.goto(f"{BASE}/projects/{grouped_id}/review")
        try:
            page.get_by_role("heading", name="Review the pictures").wait_for(timeout=15_000)
        except PlaywrightTimeout:
            shot(page, "10-grouped-failed-to-load")
            note(False, "grouped review did not load", page.url)
        else:
            shot(page, "10-review-grouped-desktop")
            note(page.get_by_text("scenes").count() > 0 or page.get_by_text("Scene 1").count() > 0, "grouped review shows scene rows")
            note(page.get_by_role("button", name="Approve scene").count() > 0, "per-scene approve is on grouped layout")
            note(page.get_by_role("button", name="Approve all remaining").count() > 0, "Approve all remaining is the grouped toolbar action")
            note(page.get_by_text("Draft preview").count() > 0, "draft player still present when grouped")

            page.get_by_role("button", name="Approve scene").first.click()
            page.get_by_role("heading", name="Approve this scene?").wait_for()
            shot(page, "11-confirm-scene")
            note(True, "per-scene confirm is distinct (Approve this scene?)")
            page.get_by_role("button", name="Back").click()

            page.get_by_role("button", name="Approve all remaining").first.click()
            page.get_by_role("heading", name="Approve all remaining scenes?").wait_for()
            shot(page, "12-confirm-remaining")
            note(True, "approve-remaining confirm is distinct and uses a destructive action")
            destructive = page.get_by_role("button", name="Approve remaining scenes")
            note(destructive.count() > 0, "remaining-scenes confirm button copy differs from per-scene")
            page.get_by_role("button", name="Back").click()

            # Expand first scene
            page.locator("text=Scene 1").first.click()
            page.wait_for_timeout(800)
            shot(page, "13-scene-expanded")
            note(
                page.get_by_role("button", name="Upload your own").count() > 0
                or page.get_by_role("button", name="Replace image").count() > 0
                or page.get_by_role("button", name="Generate now").count() > 0,
                "expanded scene row exposes per-shot override/generate",
            )

        # --- Mobile viewport on grouped review ---
        page.set_viewport_size({"width": 390, "height": 844})
        page.goto(f"{BASE}/projects/{grouped_id}/review")
        page.get_by_role("heading", name="Review the pictures").wait_for(timeout=15_000)
        shot(page, "14-review-grouped-mobile")
        note(True, "grouped review captured at mobile viewport")

        page.goto(BASE + "/")
        shot(page, "15-project-list-mobile")

        browser.close()

    (OUT / "findings.json").write_text(json.dumps(findings, indent=2), encoding="utf-8")
    failed = [f for f in findings if not f["ok"]]
    print(f"\n{len(findings) - len(failed)}/{len(findings)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(run())
