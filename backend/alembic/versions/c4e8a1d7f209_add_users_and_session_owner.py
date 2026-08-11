"""add_users_and_session_owner

Revision ID: c4e8a1d7f209
Revises: b2d5f8c1a3e6
Create Date: 2026-08-07 00:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c4e8a1d7f209"
down_revision: Union[str, Sequence[str], None] = "b2d5f8c1a3e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    # owner_id is added NOT NULL directly — this assumes sessions/evaluations
    # were already truncated as a manual rollout step before running this
    # migration (see rollout notes in the plan). Deliberately not done here:
    # a migration file should never silently execute a destructive TRUNCATE.
    op.add_column(
        "sessions",
        sa.Column(
            "owner_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
    )
    op.create_index("ix_sessions_owner_id", "sessions", ["owner_id"])


def downgrade() -> None:
    op.drop_index("ix_sessions_owner_id", table_name="sessions")
    op.drop_column("sessions", "owner_id")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
