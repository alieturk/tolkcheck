"""add_user_lockout_and_token_version

BIO2 5.17: account lockout after repeated failed logins (failed_login_count,
locked_until) and token revocation (token_version, embedded in every JWT as
"ver"; bumped on logout and deactivation).

Existing tokens carry no "ver" claim and are rejected after this upgrade, so
every user logs in once more.

Revision ID: i2f8b6d3e5a7
Revises: h7d2e4a9c1b3
Create Date: 2026-10-01 17:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'i2f8b6d3e5a7'
down_revision: Union[str, Sequence[str], None] = 'h7d2e4a9c1b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("failed_login_count", sa.Integer(),
                                     nullable=False, server_default="0"))
    op.add_column("users", sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("token_version", sa.Integer(),
                                     nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("users", "token_version")
    op.drop_column("users", "locked_until")
    op.drop_column("users", "failed_login_count")
