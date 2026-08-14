"""DomainEvent — append-only. Never updated, never deleted."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain_event import DomainEventModel


class DomainEventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def emit(self, project_id: uuid.UUID, event_type: str, payload: dict) -> None:
        self._session.add(
            DomainEventModel(project_id=project_id, event_type=event_type, payload=payload)
        )
        await self._session.flush()
