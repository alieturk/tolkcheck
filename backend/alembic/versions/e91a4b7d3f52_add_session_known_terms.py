"""add_session_known_terms

Revision ID: e91a4b7d3f52
Revises: d7f4b2c91a3e
Create Date: 2026-08-19 00:00:00.000000

Adds Session.known_terms — an optional free-text glossary (client name, place
names, case-specific terms) IND staff can supply at upload time. Threaded
through to Whisper as `initial_prompt` on every transcribe_chunk() call (see
app/services/transcription.py, app/pipeline.py) to cut down on ASR
mis-transcription of proper nouns, which otherwise manufactures LaBSE score
noise indistinguishable from a real interpreter deviation.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e91a4b7d3f52"
down_revision: Union[str, Sequence[str], None] = "d7f4b2c91a3e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("sessions", sa.Column("known_terms", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("sessions", "known_terms")
