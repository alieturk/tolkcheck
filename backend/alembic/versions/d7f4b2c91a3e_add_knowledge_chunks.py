"""add_knowledge_chunks

Revision ID: d7f4b2c91a3e
Revises: c4e8a1d7f209
Create Date: 2026-08-19 00:00:00.000000

Adds the knowledge_chunks table backing retrieval-augmented feedback
generation (see app/services/retrieval.py). Requires the pgvector extension —
this migration enables it, but the Postgres image itself must ship the
extension's binaries. docker-compose.yml's db service was switched from
postgres:16-alpine to pgvector/pgvector:pg16 for this reason; run
`docker compose pull db` (or rebuild) before running this migration against
a dev/prod stack that was created with the old image.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "d7f4b2c91a3e"
down_revision: Union[str, Sequence[str], None] = "c4e8a1d7f209"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EMBEDDING_DIM = 768  # LaBSE — must match app/models/knowledge.py


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "knowledge_chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source_id", sa.String(128), nullable=False),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_knowledge_chunks_source_id", "knowledge_chunks", ["source_id"])
    op.create_index("ix_knowledge_chunks_category", "knowledge_chunks", ["category"])

    # HNSW rather than IVFFlat: IVFFlat needs a representative sample of rows
    # present *before* the index is built, to train its cluster centroids —
    # awkward for a knowledge base that starts near-empty and grows a handful
    # of documents at a time. HNSW builds incrementally and has no such
    # minimum, at the cost of slower inserts at large scale — irrelevant here.
    op.execute(
        "CREATE INDEX ix_knowledge_chunks_embedding_hnsw "
        "ON knowledge_chunks USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_knowledge_chunks_embedding_hnsw")
    op.drop_index("ix_knowledge_chunks_category", table_name="knowledge_chunks")
    op.drop_index("ix_knowledge_chunks_source_id", table_name="knowledge_chunks")
    op.drop_table("knowledge_chunks")
    # Deliberately not dropping the vector extension — other objects created
    # after this migration may depend on it, and DROP EXTENSION would cascade.
