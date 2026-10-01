"""drop_session_scores_add_audio_deleted_at

EIS-2 (no judgement of the interpreter): drops the five per-session score
columns from evaluations. Four of them held the same number (mean LaBSE
similarity x 100) and the UI presented it as a grade (Goed / Voldoende /
Controle vereist). Per-utterance scores stay in semantic_similarity_scores.

EIS-5 (process-and-delete): adds sessions.audio_deleted_at, set when the
pipeline removes the uploaded audio at a terminal status.

Downgrade restores the score columns empty (the dropped values are not
recoverable) and drops audio_deleted_at.

Revision ID: h7d2e4a9c1b3
Revises: g4b9d1e5c2f7a
Create Date: 2026-10-01 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'h7d2e4a9c1b3'
down_revision: Union[str, Sequence[str], None] = 'g4b9d1e5c2f7a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SCORE_COLUMNS = (
    "overall_score",
    "accuracy_score",
    "completeness_score",
    "terminology_score",
    "fluency_score",
)


def upgrade() -> None:
    for name in _SCORE_COLUMNS:
        op.drop_column("evaluations", name)
    op.add_column(
        "sessions",
        sa.Column("audio_deleted_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sessions", "audio_deleted_at")
    for name in _SCORE_COLUMNS:
        op.add_column("evaluations", sa.Column(name, sa.Float(), nullable=True))
