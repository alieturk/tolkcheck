"""initial_schema

Revision ID: 49c2a9c9e9ee
Revises:
Create Date: 2026-04-17 11:17:08.575387

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "49c2a9c9e9ee"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

session_status = postgresql.ENUM(
    "pending",
    "transcribing",
    "diarising",
    "awaiting_role_confirmation",
    "scoring",
    "generating",
    "completed",
    "failed",
    name="sessionstatus",
)


def upgrade() -> None:
    session_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("audio_path", sa.String(512), nullable=False),
        sa.Column("language", sa.String(10), nullable=False, server_default="nl"),
        sa.Column("ind_case_id", sa.String(100), nullable=True),
        sa.Column(
            "status",
            session_status,
            nullable=False,
            server_default="pending",
        ),
        sa.Column("duration_seconds", sa.Float, nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_table(
        "evaluations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sessions.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("interpreter_speaker", sa.String(32), nullable=True),
        sa.Column("client_speaker", sa.String(32), nullable=True),
        sa.Column("overall_score", sa.Float, nullable=True),
        sa.Column("accuracy_score", sa.Float, nullable=True),
        sa.Column("completeness_score", sa.Float, nullable=True),
        sa.Column("terminology_score", sa.Float, nullable=True),
        sa.Column("fluency_score", sa.Float, nullable=True),
        sa.Column("transcript", postgresql.JSONB, nullable=True),
        sa.Column("semantic_similarity_scores", postgresql.JSONB, nullable=True),
        sa.Column("llm_feedback", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_evaluations_session_id", "evaluations", ["session_id"])


def downgrade() -> None:
    op.drop_index("ix_evaluations_session_id", table_name="evaluations")
    op.drop_table("evaluations")
    op.drop_table("sessions")
    session_status.drop(op.get_bind(), checkfirst=True)
