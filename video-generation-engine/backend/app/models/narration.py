"""Narration — synthesized TTS audio for one scene's `narration_text`
(M8, D1). One row per (scene, voice, model, output_format) combination
actually synthesised; `content_hash` is the cache key.

`content_hash` uniqueness is GLOBAL, not per-project - same discipline as
`generated_clip.prompt_hash` (ladder rung 0). Synthesising identical text
with the identical voice/model/output_format/speed is a wasted paid call
no matter which project asks for it, and ElevenLabs bills per character
either way. See `providers/elevenlabs.compute_narration_content_hash` for
how the hash is built and why it excludes the returned audio bytes and
alignment (the hash must be knowable BEFORE the paid call, so a cache hit
can skip the call entirely). Speed 1.0 is omitted from the digest so
pre-R8 rows remain hits at the API default.

`alignment` stores the RAW (non-normalized) alignment object returned by
ElevenLabs' `/with-timestamps` endpoint - never `normalized_alignment`,
whose character indices no longer correspond to the scene's
`narration_text` (see `providers/elevenlabs.py`). `character_count` is the
billed length of the input text and `cost_cents` its estimated cost,
recorded so a later step can fold narration spend into `app/assets/
cost.py`'s project budget cap the same way `generated_clip.cost_cents`
already does.

Unlike `GeneratedClip`, there is no submit/poll pending state here:
ElevenLabs' timestamped endpoint is request-response, not a queue, so a
row is only ever inserted once the audio and alignment already exist.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class NarrationModel(Base):
    __tablename__ = "narration"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project.id"), nullable=False
    )
    scene_id: Mapped[str] = mapped_column(String, nullable=False)  # matches IR scene id
    provider: Mapped[str] = mapped_column(String, nullable=False)
    voice_id: Mapped[str] = mapped_column(String, nullable=False)
    model_id: Mapped[str] = mapped_column(String, nullable=False)
    output_format: Mapped[str] = mapped_column(String, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    local_path: Mapped[str] = mapped_column(String, nullable=False)
    alignment: Mapped[dict] = mapped_column(JSONB, nullable=False)
    character_count: Mapped[int] = mapped_column(Integer, nullable=False)
    cost_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
