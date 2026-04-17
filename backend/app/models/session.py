from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, Float, String, Text, func
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
    filename: Mapped[str] = mapped_column(String(255))
    audio_path: Mapped[str] = mapped_column(String(512))
    language: Mapped[str] = mapped_column(String(10), default="nl")
    ind_case_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[SessionStatus] = mapped_column(
        Enum(SessionStatus), default=SessionStatus.PENDING
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
