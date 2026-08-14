"""Local project asset provider (M6, ladder rung `project_assets` - media
the user already uploaded for this specific project).

Stub: there is no project-asset upload endpoint yet, so this always
returns no candidates and the ladder falls through to the next rung. It
exists as a real, wired-in class - not a TODO comment - so adding the
upload feature later is a change to this one file, not to the ladder
logic in `resolve_assets.py`.
"""

from app.providers.base import AssetBytes, AssetCandidate, AssetQuery


class LocalProjectAssetProvider:
    name = "project_assets"
    rung = "project_assets"

    async def search(self, query: AssetQuery) -> list[AssetCandidate]:
        return []

    async def fetch(self, candidate: AssetCandidate) -> AssetBytes:
        raise NotImplementedError("LocalProjectAssetProvider never returns candidates to fetch")
