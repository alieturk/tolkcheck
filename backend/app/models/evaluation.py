from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, JSON, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Evaluation(Base):
    __tablename__ = "evaluations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sessions.id", ondelete="CASCADE"),
        unique=True,
        index=True,
    )

    # Speaker role assignment — set by the user at the confirmation step
    interpreter_speaker: Mapped[str | None] = mapped_column(String(32), nullable=True)
    client_speaker: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # Scores — 0 to 100 (null until Phase B of the pipeline completes)
    overall_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    accuracy_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    completeness_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    terminology_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    fluency_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    # AI pipeline outputs
    # transcript: list of {start, end, speaker, text} — stored after diarisation
    transcript: Mapped[list | None] = mapped_column(JSON, nullable=True)
    semantic_similarity_scores: Mapped[list | None] = mapped_column(JSON, nullable=True)
    llm_feedback: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
