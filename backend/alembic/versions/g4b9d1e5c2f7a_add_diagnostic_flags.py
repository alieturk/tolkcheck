"""add_diagnostic_flags

Adds diagnostic fields to evaluations for surfacing Tier 1, 2 & 3 fixes:

Tier 1:
- short_turns_skipped (int): count of turns < 50ms skipped during Phase A transcription
- language_confidence (str): "high" or "low" based on language detection success
- language_validation_passed (bool): false if forced language in Phase B retranscription
  resulted in <70% of segments in the expected language

Tier 2:
- timestamp_mapping_issues (int, nullable): count of segments that had remapping issues
  (fell in gaps or straddled boundaries) during Phase B retranscription chunk processing

Tier 3 (Fix #8):
- asr_confidence_distribution (JSONB, nullable): per-direction ASR confidence scores
  {"o2c": [0.95, 0.87, ...], "c2o": [0.88, 0.91, ...]}
  Replaces binary reliability flag with continuous 0-1 confidence scores

These flags are written during the pipeline and displayed in the evaluation view to
alert users when diagnostic confidence is lower.

Revision ID: g4b9d1e5c2f7a
Revises: f3a9c62b810d
Create Date: 2026-09-24 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'g4b9d1e5c2f7a'
down_revision: Union[str, Sequence[str], None] = 'f3a9c62b810d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "evaluations",
        sa.Column("short_turns_skipped", sa.Integer(), nullable=False, server_default='0'),
    )
    op.add_column(
        "evaluations",
        sa.Column("language_confidence", sa.String(10), nullable=False, server_default='high'),
    )
    op.add_column(
        "evaluations",
        sa.Column("language_validation_passed", sa.Boolean(), nullable=False, server_default='true'),
    )
    op.add_column(
        "evaluations",
        sa.Column("timestamp_mapping_issues", sa.Integer(), nullable=True),
    )
    op.add_column(
        "evaluations",
        sa.Column("asr_confidence_distribution", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("evaluations", "asr_confidence_distribution")
    op.drop_column("evaluations", "timestamp_mapping_issues")
    op.drop_column("evaluations", "language_validation_passed")
    op.drop_column("evaluations", "language_confidence")
    op.drop_column("evaluations", "short_turns_skipped")
