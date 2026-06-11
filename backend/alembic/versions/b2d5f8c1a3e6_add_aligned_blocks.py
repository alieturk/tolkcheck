"""add_aligned_blocks

Revision ID: b2d5f8c1a3e6
Revises: a1c3e7f9b2d4
Create Date: 2026-06-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'b2d5f8c1a3e6'
down_revision: Union[str, Sequence[str], None] = 'a1c3e7f9b2d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('evaluations',
                  sa.Column('aligned_blocks',
                            postgresql.JSONB(astext_type=sa.Text()),
                            nullable=True))


def downgrade() -> None:
    op.drop_column('evaluations', 'aligned_blocks')
