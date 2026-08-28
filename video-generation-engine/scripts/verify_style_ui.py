"""Playwright pass over the style/feature UI (ui_style_feature_coverage.md).

Vite must be running at http://localhost:5173. Backend is optional: /new
is fully exercisable without it; Result/Review need a live API.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "tmp" / "style-ui-verify"
BASE = "http://localhost:5173"

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


def run() -> int:
    OUT.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 900})
        page = context.new_page()
        page.set_default_timeout(10_000)

        page.goto(BASE + "/new")
        page.get_by_role("heading", name="New project").wait_for()

        for label in (
            "Archival documentary",
            "Fast-cut reel",
            "Stillness",
            "Archival montage",
        ):
            btn = page.get_by_role("button", name=label)
            note(btn.count() == 1, f"style card present: {label}")

        montage = page.get_by_role("button", name="Archival montage")
        montage.click()
        note(montage.get_attribute("aria-pressed") == "true", "archival_montage is selectable")
        note(
            page.get_by_role("heading", name="Frame").count() == 0,
            "frame-aspect toggle stays hidden for archival_montage",
        )
        shot(page, "01-new-project-montage-desktop")

        page.get_by_role("button", name="Stillness").click()
        note(
            page.get_by_text("16:9 landscape").count() > 0,
            "stillness reveals the frame-aspect picker",
        )
        page.get_by_role("button", name="9:16 portrait").click()
        note(
            page.get_by_role("button", name="9:16 portrait").get_attribute("aria-pressed")
            == "true",
            "9:16 frame-aspect OptionCard works",
        )
        shot(page, "02-new-project-stillness-frame")

        hindi = page.get_by_role("button", name="Hindi / Hinglish")
        note(hindi.get_attribute("aria-pressed") == "true", "language OptionCard default is Hindi")
        page.get_by_role("button", name="Spanish").click()
        note(
            page.get_by_role("button", name="Spanish").get_attribute("aria-pressed") == "true",
            "language OptionCard is selectable",
        )

        previews = page.locator("img[src*='/style-previews/']")
        note(previews.count() == 4, "four style preview stills rendered", f"count={previews.count()}")

        page.set_viewport_size({"width": 390, "height": 844})
        shot(page, "03-new-project-mobile")
        note(
            page.get_by_role("button", name="Archival montage").is_visible(),
            "archival_montage still visible at mobile width",
        )

        page.set_viewport_size({"width": 1280, "height": 900})
        try:
            page.goto(BASE + "/")
            page.wait_for_timeout(1500)
            shot(page, "04-project-list")
            note(page.get_by_role("heading", name="Projects").count() > 0, "project list heading")
        except PlaywrightTimeout:
            note(False, "project list did not load")

        # Read-only live pages. Never click Apply grade / Retry SFX /
        # Generate video / Re-render — those mutate the shared DB.
        RESULT_ID = "058b0e05-8468-42cc-81ae-01d3ebdb3478"
        REVIEW_ID = "3d56cf87-1322-42a6-b29a-9ddb7cd05747"

        page.goto(BASE + f"/projects/{RESULT_ID}/result")
        try:
            page.get_by_role("heading", name="Automatic transmissions").wait_for(timeout=20_000)
            shot(page, "05-result-desktop")
            note(page.get_by_text("Fast-cut reel").count() > 0, "result shows render style label")
            note(page.get_by_text("Word-highlight captions").count() > 0, "result names caption treatment")
            note(page.get_by_text("Colour grade").count() > 0, "result has grade card")
            note(page.get_by_text("Match this project's style").count() > 0, "grade has Match-style reset")
            note(page.get_by_text("Sound effects").count() > 0, "result has SFX card")
            note(page.get_by_role("button", name="Apply grade").count() > 0, "Apply grade is present (not clicked)")
            note(page.get_by_role("button", name="Retry SFX selection").count() > 0, "Retry SFX is present (not clicked)")
        except PlaywrightTimeout:
            shot(page, "05-result-timeout")
            note(False, "result page did not load", page.url)

        page.set_viewport_size({"width": 390, "height": 844})
        page.goto(BASE + f"/projects/{RESULT_ID}/result")
        page.wait_for_timeout(2000)
        shot(page, "06-result-mobile")
        page.set_viewport_size({"width": 1280, "height": 900})

        page.goto(BASE + f"/projects/{REVIEW_ID}/review")
        try:
            page.get_by_role("heading", name="Review the pictures").wait_for(timeout=20_000)
            shot(page, "07-review-desktop")
            note(page.get_by_text("punch in").count() > 0, "review shows camera movement")
            note(page.get_by_text("out: cut").count() > 0, "review shows transition_out")
            note(page.get_by_role("button", name="Generate video").count() > 0, "Generate video is present (not clicked)")
        except PlaywrightTimeout:
            shot(page, "07-review-timeout")
            note(False, "review page did not load", page.url)

        browser.close()

    (OUT / "findings.json").write_text(json.dumps(findings, indent=2), encoding="utf-8")
    failed = sum(1 for f in findings if not f["ok"])
    print(f"\n{len(findings) - failed}/{len(findings)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(run())
