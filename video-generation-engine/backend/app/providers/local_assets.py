"""Local project asset provider (M6, ladder rung `project_assets` - media
the user already uploaded for this specific project).

M6.5 (A8/A23): every asset a human uploaded for this project - through
`POST /projects/{id}/assets`, or as the by-product of a per-shot override
(A9/A24 stores its file the same way) - is a candidate here. There is no
search API to call: `search` just hands back every upload this project
has (`AssetRepository.list_uploads_for_project`) and lets
`ResolveAssetsStep` run them through the SAME relevance gate
(`app/assets/relevance.py`) every other provider's results go through,
scored against the shot's search terms and each upload's own
human-written `description` (A23 - matching against a filename would be
worthless, which is why an upload requires a description at all). Never
filtered here: the whole point of A23 is that an upload competes on the
same terms as a search result, through the one existing scoring path,
not a second one, and never via a planner (A3 stands).

A project with no uploads gets `[]` back, exactly like the pre-M6.5 stub
- the ladder falls through to the next rung, unchanged.
"""

import uuid
from pathlib import Path

from app.core.errors import PermanentError
from app.providers.base import AssetBytes, AssetCandidate, AssetQuery
from app.repositories.asset_repository import AssetRepository

# Deliberately a private copy, not imported from `app/assets/validation.py`:
# the dependency rule (implementation guide section 5) is `assets ->
# providers`, never the reverse - a provider must not import upward from
# `assets/`. `app/assets/validation.mime_type_for_extension` is the
# equivalent table for callers that already sit above `providers/` (e.g.
# `app/workflow/steps/resolve_assets.py`, M6.5 A30).
_CONTENT_TYPE_BY_EXTENSION = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
    "gif": "image/gif",
    "bmp": "image/bmp",
    "tiff": "image/tiff",
}


class LocalProjectAssetProvider:
    name = "project_assets"
    rung = "project_assets"

    def __init__(self, asset_repo: AssetRepository, project_id: uuid.UUID) -> None:
        self._asset_repo = asset_repo
        self._project_id = project_id

    async def search(self, query: AssetQuery) -> list[AssetCandidate]:
        uploads = await self._asset_repo.list_uploads_for_project(self._project_id)
        return [
            AssetCandidate(
                source_id=str(upload.id),
                source_url=upload.source_url or "",
                title=upload.description or "",
                licence=upload.licence,
                description=upload.description or "",
                author=upload.attribution or "",
            )
            for upload in uploads
        ]

    async def fetch(self, candidate: AssetCandidate) -> AssetBytes:
        asset = await self._asset_repo.get_by_id(uuid.UUID(candidate.source_id))
        if asset is None or not asset.local_path:
            raise PermanentError(f"uploaded asset {candidate.source_id} has no stored bytes")
        path = Path(asset.local_path)
        if not path.exists():
            raise PermanentError(f"uploaded asset {candidate.source_id} is missing on disk")
        extension = path.suffix.lstrip(".").lower()
        content_type = _CONTENT_TYPE_BY_EXTENSION.get(extension, "image/png")
        return AssetBytes(
            content=path.read_bytes(),
            content_type=content_type,
            attribution=asset.attribution or "",
        )
