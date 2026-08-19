from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, Float, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SessionStatus(str, enum.Enum):
    PENDING                    = "pending"
    TRANSCRIBING               = "transcribing"
    DIARISING                  = "diarising"
    AWAITING_ROLE_CONFIRMATION = "awaiting_role_confirmation"
    SCORING                    = "scoring"
    GENERATING                 = "generating"
    COMPLETED                  = "completed"
    FAILED                     = "failed"


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), index=True
    )
    filename: Mapped[str] = mapped_column(String(255))
    audio_path: Mapped[str] = mapped_column(String(512))
    language: Mapped[str] = mapped_column(String(10), default="nl")
    ind_case_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Optional free-text glossary (client name, place names, case-specific
    # terms) supplied by IND staff at upload time. Passed to Whisper as
    # `initial_prompt` on every transcribe_chunk() call in pipeline.py — see
    # app/services/transcription.py. Purely a transcription-quality aid: never
    # shown to the LLM feedback step, never scored.
    known_terms: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[SessionStatus] = mapped_column(
        Enum(SessionStatus, values_callable=lambda x: [e.value for e in x]),
        default=SessionStatus.PENDING,
    )
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Machine-readable code shown to the user as a localised Dutch message
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Raw Python exception — for debugging only, never shown in the UI
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
