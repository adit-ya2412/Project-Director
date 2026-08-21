"""Download a small CC0/CC-BY SFX library via Openverse (plan §5.5).

Three kinds × up to 3 short clips. Writes storage/sfx_library/manifest.json
and the mp3 files. Run from backend/:

    ../.venv/Scripts/python.exe scripts/download_sfx_library.py
    ../.venv/Scripts/python.exe scripts/download_sfx_library.py --fill-short

`--fill-short` does not rebuild the library. For each kind that has no
clip at or under `settings.sfx_max_clip_s` (the mix trim), it appends
one CC0/CC-BY clip that fits intact (R15 library residual).
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path

import httpx

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))

from app.core.config import settings  # noqa: E402
from app.renderer.slideshow import probe_duration_seconds  # noqa: E402

_API = "https://api.openverse.org/v1/audio/"
_ACCEPTABLE = frozenset({"cc0", "by"})
_LIBRARY = _BACKEND / "storage" / "sfx_library"
_QUERIES = {
    "whoosh": ["whoosh", "swoosh"],
    "stinger": ["stinger", "cinematic hit"],
    "transition": ["swoosh", "whoosh transition"],
}
# Extra terms used only by `--fill-short`. The bulk queries above
# returned no stinger under the mix ceiling; these do.
_SHORT_QUERIES = {
    "stinger": ["timpani sting", "brass sting", "orchestra hit"],
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
                    if isinstance(duration_ms, int | float) and duration_ms > _MAX_DURATION_S * 1000:
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

    _write_manifest(entries)
    return 0 if entries else 1


def _write_manifest(entries: list[dict]) -> None:
    manifest = _LIBRARY / "manifest.json"
    manifest.write_text(json.dumps(entries, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("wrote", manifest, "count", len(entries))


async def fill_short_gaps() -> int:
    """Append one mix-intact clip per kind that currently has none.

    Does not rewrite existing files. Whoosh and transition already have
    clips under the ceiling; stinger did not (R15 residual).
    """
    manifest_path = _LIBRARY / "manifest.json"
    entries: list[dict] = json.loads(manifest_path.read_text(encoding="utf-8"))
    seen_ids = {str(entry.get("source_url") or "") for entry in entries}
    seen_files = {str(entry.get("file") or "") for entry in entries}
    ceiling = settings.sfx_max_clip_s
    headers = {"User-Agent": "video-generation-engine/0.1 (sfx library curation)"}
    added = 0
    with httpx.Client(headers=headers) as client:
        for kind, fallback_terms in _QUERIES.items():
            existing = [e for e in entries if e.get("kind") == kind]
            if any(
                isinstance(e.get("duration_s"), int | float) and e["duration_s"] <= ceiling
                for e in existing
            ):
                print(f"{kind}: already has a clip <= {ceiling}s")
                continue
            terms = list(_SHORT_QUERIES.get(kind) or []) + list(fallback_terms)
            kept_this_kind = False
            for term in terms:
                if kept_this_kind:
                    break
                try:
                    results = _search(client, term)
                except httpx.HTTPError as exc:
                    print(f"search failed {kind!r} {term!r}: {exc}")
                    continue
                # CC0 first, then CC-BY, so the residual's "one CC0 stinger" wins.
                results = sorted(
                    results,
                    key=lambda item: 0 if (item.get("license") or "").lower() == "cc0" else 1,
                )
                for result in results:
                    if kept_this_kind:
                        break
                    ident = str(result.get("id") or "")
                    landing = str(result.get("foreign_landing_url") or result.get("url") or "")
                    if not ident or landing in seen_ids:
                        continue
                    licence = (result.get("license") or "").lower()
                    if licence not in _ACCEPTABLE:
                        continue
                    url = result.get("url")
                    if not url:
                        continue
                    duration_ms = result.get("duration")
                    if isinstance(duration_ms, int | float) and duration_ms > ceiling * 1000:
                        continue
                    content = _download(client, url)
                    if content is None:
                        continue
                    title = result.get("title") or ident
                    filename = f"{_slug(title)}.mp3"
                    rel = f"{kind}/{filename}"
                    if rel in seen_files:
                        filename = f"{_slug(title)}_{ident[:8]}.mp3"
                        rel = f"{kind}/{filename}"
                    path = _LIBRARY / rel
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(content)
                    duration = await _duration(path)
                    if duration is None or duration < _MIN_DURATION_S or duration > ceiling:
                        path.unlink(missing_ok=True)
                        continue
                    seen_ids.add(landing)
                    seen_files.add(rel)
                    entries.append(
                        {
                            "file": rel,
                            "title": title,
                            "artist": result.get("creator") or "unknown",
                            "source": "openverse",
                            "source_url": landing or url,
                            "license": licence,
                            "kind": kind,
                            "duration_s": round(duration, 3),
                            "tags": kind,
                            "attribution": result.get("attribution") or "",
                        }
                    )
                    added += 1
                    kept_this_kind = True
                    print(f"kept {rel} {duration:.2f}s {licence}")
            if not kept_this_kind:
                print(f"{kind}: no mix-intact clip found")
                if added:
                    _write_manifest(entries)
                return 1

    if added:
        _write_manifest(entries)
    return 0


if __name__ == "__main__":
    if "--fill-short" in sys.argv:
        raise SystemExit(asyncio.run(fill_short_gaps()))
    raise SystemExit(asyncio.run(main()))
