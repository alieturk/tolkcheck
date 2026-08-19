"""Knowledge base chunks for retrieval-augmented feedback generation (RAG).

Populated via `uv run python -m app.cli ingest-knowledge knowledge_base` from
the curated corpus under backend/knowledge_base/ — see that directory's
README for what is in it, what is still missing, and each source's
verification status. Nothing here is scraped or generated automatically:
every row traces back to a source a human opened and checked, or is
explicitly marked as not yet fully verified (see knowledge_base/README.md).
"""
from __future__ import annotations

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

# Must match the output dimensionality of the model in app/services/embeddings.py
# (LaBSE = 768). If that model ever changes, this column and every existing
# row's vector need re-embedding — they are not interchangeable across models.
EMBEDDING_DIM = 768


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # Stable slug for the source document, e.g. "euaa-2024-asielgehoor-structuur".
    # Re-ingesting a file with the same source_id replaces its chunks (see
    # app/services/retrieval.py:ingest_source).
    source_id: Mapped[str] = mapped_column(String(128), index=True)
    # One of: taxonomy | ind_procedure | linguistic_case — see knowledge_base/README.md
    category: Mapped[str] = mapped_column(String(32), index=True)
    # Full citation string, shown to the LLM and — if it cites the chunk — to
    # the IND officer reading the feedback. Keep this pasteable as-is.
    title: Mapped[str] = mapped_column(String(512))
    content: Mapped[str] = mapped_column(Text)
    # url/authors/year/language/verification status/chunk_index, etc.
    meta: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
