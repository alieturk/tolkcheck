from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
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
    transcript: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # aligned_blocks: full block sequence with direction classification — stored after Phase B alignment
    aligned_blocks: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # role_warnings: output of services/role_check.py — language distribution per
    # speaker plus any warning that the confirmed role assignment contradicts it.
    # Written before scoring so a hearing whose speakers were mixed up is visible
    # as such rather than silently producing ordinary-looking numbers.
    role_warnings: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    semantic_similarity_scores: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    client_translations: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    llm_feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    structured_issues: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    # Diagnostic flags from Phase A/B — surface issues to the frontend
    short_turns_skipped: Mapped[int] = mapped_column(default=0)
    language_confidence: Mapped[str] = mapped_column(String(10), default="high")
    language_validation_passed: Mapped[bool] = mapped_column(default=True)
    timestamp_mapping_issues: Mapped[int | None] = mapped_column(nullable=True)
    # ASR confidence scores per direction (Tier 3 fix #8)
    asr_confidence_distribution: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
