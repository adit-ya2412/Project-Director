"""Download a small CC0/CC-BY SFX library via Openverse (plan §5.5).

Three kinds × up to 3 short clips. Writes storage/sfx_library/manifest.json
and the mp3 files. Run from backend/:

    ../.venv/Scripts/python.exe scripts/download_sfx_library.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import httpx

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))

from app.core.config import settings  # noqa: E402
from app.renderer.slideshow import probe_duration_seconds  # noqa: E402
import asyncio  # noqa: E402

_API = "https://api.openverse.org/v1/audio/"
_ACCEPTABLE = frozenset({"cc0", "by"})
_LIBRARY = _BACKEND / "storage" / "sfx_library"
_QUERIES = {
    "whoosh": ["whoosh", "swoosh"],
    "stinger": ["stinger", "cinematic hit"],
    "transition": ["swoosh", "whoosh transition"],
}
_PER_KIND = 3
_MAX_DURATION_S = 4.0
_MIN_DURATION_S = 0.08


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return slug[:60] or "clip"


def _search(client: httpx.Client, term: str) -> list[dict]:
    response = client.get(
        _API,
        params={"q": term, "license": "cc0,by", "page_size": "20"},
        timeout=30.0,
    )
    response.raise_for_status()
    return list(response.json().get("results") or [])


def _download(client: httpx.Client, url: str) -> bytes | None:
    try:
        response = client.get(url, follow_redirects=True, timeout=60.0)
        response.raise_for_status()
    except httpx.HTTPError:
        return None
    content_type = (response.headers.get("content-type") or "").lower()
    if "html" in content_type:
        return None
    if len(response.content) < 1000:
        return None
    return response.content


async def _duration(path: Path) -> float | None:
    try:
        return await probe_duration_seconds(path, settings.ffprobe_binary)
    except Exception:
        return None


async def main() -> int:
    _LIBRARY.mkdir(parents=True, exist_ok=True)
    entries: list[dict] = []
    seen_ids: set[str] = set()
    headers = {"User-Agent": "video-generation-engine/0.1 (sfx library curation)"}
    with httpx.Client(headers=headers) as client:
        for kind, terms in _QUERIES.items():
            kind_dir = _LIBRARY / kind
            kind_dir.mkdir(parents=True, exist_ok=True)
            kept = 0
            for term in terms:
                if kept >= _PER_KIND:
                    break
                try:
                    results = _search(client, term)
                except httpx.HTTPError as exc:
                    print(f"search failed {kind!r} {term!r}: {exc}")
                    continue
                for result in results:
                    if kept >= _PER_KIND:
                        break
                    ident = str(result.get("id") or "")
                    if not ident or ident in seen_ids:
                        continue
                    licence = (result.get("license") or "").lower()
                    if licence not in _ACCEPTABLE:
                        continue
                    url = result.get("url")
                    if not url:
                        continue
                    duration_ms = result.get("duration")
                    if isinstance(duration_ms, (int, float)) and duration_ms > _MAX_DURATION_S * 1000:
                        continue
                    content = _download(client, url)
                    if content is None:
                        continue
                    title = result.get("title") or ident
                    filename = f"{_slug(title)}.mp3"
                    path = kind_dir / filename
                    if path.exists():
                        filename = f"{_slug(title)}_{ident[:8]}.mp3"
                        path = kind_dir / filename
                    path.write_bytes(content)
                    duration = await _duration(path)
                    if duration is None or duration < _MIN_DURATION_S or duration > _MAX_DURATION_S:
                        path.unlink(missing_ok=True)
                        continue
                    seen_ids.add(ident)
                    rel = f"{kind}/{filename}"
                    entries.append(
                        {
                            "file": rel,
                            "title": title,
                            "artist": result.get("creator") or "unknown",
                            "source": "openverse",
                            "source_url": result.get("foreign_landing_url") or url,
                            "license": licence,
                            "kind": kind,
                            "duration_s": round(duration, 3),
                            "tags": kind,
                            "attribution": result.get("attribution") or "",
                        }
                    )
                    kept += 1
                    print(f"kept {rel} {duration:.2f}s {licence}")
            print(f"{kind}: {kept}/{_PER_KIND}")

    manifest = _LIBRARY / "manifest.json"
    manifest.write_text(json.dumps(entries, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("wrote", manifest, "count", len(entries))
    return 0 if entries else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
