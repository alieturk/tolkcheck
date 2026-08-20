"""add_role_warnings

Adds evaluations.role_warnings — the output of services/role_check.py: the
detected-language distribution per speaker plus any warning that the confirmed
role assignment contradicts it. Written before scoring so a hearing whose
speakers were mixed up by diarization is visible as such, rather than silently
producing ordinary-looking scores.

Revision ID: f3a9c62b810d
Revises: e91a4b7d3f52
Create Date: 2026-08-20 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'f3a9c62b810d'
down_revision: Union[str, Sequence[str], None] = 'e91a4b7d3f52'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "evaluations",
        sa.Column("role_warnings", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("evaluations", "role_warnings")
