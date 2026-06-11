"""add_client_translations

Revision ID: a1c3e7f9b2d4
Revises: 3b832fc0f63d
Create Date: 2026-06-08 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'a1c3e7f9b2d4'
down_revision: Union[str, Sequence[str], None] = '71fd29b45a48'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('evaluations', sa.Column('client_translations', postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column('evaluations', 'client_translations')
