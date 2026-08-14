"""Asset persistence. Dedup is per-project on content_hash (see
app/models/asset.py for why it isn't global)."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.asset import AssetModel


class AssetRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_content_hash(
        self, project_id: uuid.UUID, content_hash: str
    ) -> AssetModel | None:
        result = await self._session.execute(
            select(AssetModel).where(
                AssetModel.project_id == project_id,
                AssetModel.content_hash == content_hash,
            )
        )
        return result.scalar_one_or_none()

    async def list_content_hashes_for_project(self, project_id: uuid.UUID) -> set[str]:
        """Every asset already stored for this project - the reuse-penalty
        input for ranking (implementation guide, Phase M6 advice: "penalise
        reuse within a project... [Creative Philosophy] Principle 10 demands
        visual variety")."""
        result = await self._session.execute(
            select(AssetModel.content_hash).where(AssetModel.project_id == project_id)
        )
        return set(result.scalars().all())

    async def insert(
        self,
        *,
        project_id: uuid.UUID,
        provider: str,
        source_url: str | None,
        type: str,  # noqa: A002 - matches the column name
        local_path: str,
        licence: str,
        attribution: str | None,
        content_hash: str,
        confidence: float,
    ) -> AssetModel:
        model = AssetModel(
            project_id=project_id,
            provider=provider,
            source_url=source_url,
            type=type,
            local_path=local_path,
            licence=licence,
            attribution=attribution,
            content_hash=content_hash,
            confidence=confidence,
        )
        self._session.add(model)
        await self._session.flush()
        return model
