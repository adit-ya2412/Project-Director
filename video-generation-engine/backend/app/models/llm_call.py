"""LlmCall — full request/response for every planning call (M5).

Never call an LLM without recording the exchange here: it is what makes
planning auditable, replayable in golden-file tests, and attributable for
cost, and it is what answers "which prompt version produced this
timeline?" three weeks later.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class LlmCallModel(Base):
    __tablename__ = "llm_call"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project.id"), nullable=False
    )
    agent: Mapped[str] = mapped_column(String, nullable=False)
    # director | scene_planner | shot_planner | asset_planner
    prompt_version: Mapped[str | None] = mapped_column(String, nullable=True)
    model: Mapped[str] = mapped_column(String, nullable=False)
    request: Mapped[dict] = mapped_column(JSONB, nullable=False)
    response: Mapped[dict] = mapped_column(JSONB, nullable=False)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # None = unknown model (missing price must not look free). Rates are
    # the USD/1M used at insert time so a later price-table change does
    # not rewrite history (OQ-4.4).
    cost_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    input_usd_per_1m: Mapped[float | None] = mapped_column(Float, nullable=True)
    output_usd_per_1m: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
