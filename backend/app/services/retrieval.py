"""Retrieval-augmented context for LLM feedback generation (RAG).

Grounds generate_feedback()'s reasoning in a small curated knowledge base —
interpreting-error taxonomy, IND werkinstructies, and documented linguistic
case findings (see backend/knowledge_base/) — instead of relying solely on
Claude's own training-time knowledge. Retrieval is strictly additive: it
supplies background text the prompt may cite, it never changes a LaBSE
similarity score or the thresholds in feedback.py's system prompt. If
retrieval fails for any reason, feedback generation must still work exactly
as it did before this module existed — every call site treats retrieval
failure as non-fatal.

Storage: Postgres + pgvector (see alembic revision
d7f4b2c91a3e_add_knowledge_chunks). Embeddings reuse the LaBSE model already
loaded for scoring (app/services/embeddings.py) rather than a second model —
one ~1.8GB transformer in memory, and the knowledge base lives in the same
cross-lingual embedding space the scoring pipeline already relies on.

Populate/refresh the knowledge base with:
    uv run python -m app.cli ingest-knowledge knowledge_base
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import delete, select

from app.models.knowledge import KnowledgeChunk
from app.services.embeddings import embed_texts

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger(__name__)

# Retrieval is only worth its cost (an embedding call + a vector search) for
# pairs the score itself already flags as uncertain or wrong. This mirrors
# the ">= 0.70 = semantically correct" cut-off documented in feedback.py's
# _SYSTEM_PROMPT (see the TODO(DV4) note there about that number being
# hand-picked, not calibrated). Changing RETRIEVAL_SCORE_CEILING only changes
# what gets looked up for background context — it is NOT a scoring threshold
# and does not touch a stored score.
RETRIEVAL_SCORE_CEILING = 0.70

DEFAULT_TOP_K = 2
MAX_CONTEXT_CHUNKS = 6


# ── Query-time retrieval ──────────────────────────────────────────────────────

async def retrieve_for_pairs(
    db: AsyncSession,
    pairs: list[dict],
    scores: list[float],
    top_k: int = DEFAULT_TOP_K,
) -> list[KnowledgeChunk]:
    """Retrieve chunks relevant to the pairs scoring below RETRIEVAL_SCORE_CEILING.

    pairs/scores must be the same length and index-aligned (as produced by
    alignment.extract_pairs + scoring.score_segments).
    """
    queries = [
        f"{p['source_block']['text']} {p['interp_block']['text']}"
        for p, s in zip(pairs, scores)
        if s < RETRIEVAL_SCORE_CEILING
    ]
    return await retrieve(db, queries, top_k=top_k)


async def retrieve(
    db: AsyncSession,
    queries: list[str],
    top_k: int = DEFAULT_TOP_K,
) -> list[KnowledgeChunk]:
    """Embed each query and return the deduplicated nearest chunks overall.

    One DB round trip per query — fine at the volumes involved (a session has
    at most a few dozen pairs, and only the sub-threshold ones become
    queries). Not batched into a single query; revisit if that changes.
    """
    if not queries:
        return []
    try:
        query_vecs = await embed_texts(queries)
    except Exception:
        log.warning("retrieve  embedding failed — continuing without knowledge context",
                     exc_info=True)
        return []

    best_distance: dict = {}
    best_chunk: dict = {}
    for vec in query_vecs:
        stmt = (
            select(KnowledgeChunk, KnowledgeChunk.embedding.cosine_distance(vec).label("distance"))
            .order_by("distance")
            .limit(top_k)
        )
        try:
            result = await db.execute(stmt)
        except Exception:
            log.warning("retrieve  vector search failed — continuing without knowledge context",
                         exc_info=True)
            return []
        for chunk, distance in result.all():
            if chunk.id not in best_distance or distance < best_distance[chunk.id]:
                best_distance[chunk.id] = distance
                best_chunk[chunk.id] = chunk

    ranked = sorted(best_chunk.values(), key=lambda c: best_distance[c.id])
    return ranked[:MAX_CONTEXT_CHUNKS]


def format_context_block(chunks: list[KnowledgeChunk]) -> str:
    """Render retrieved chunks as a labelled, citable block for the LLM prompt."""
    if not chunks:
        return ""
    lines = [
        "=== ACHTERGRONDINFORMATIE (ter ondersteuning — verandert de scores hierboven niet) ===",
        "Gebruik onderstaande fragmenten alleen als ze relevant zijn voor de beoordeling. "
        "Citeer bij gebruik uitsluitend de bronvermelding die erachter staat; verzin geen "
        "andere bron.",
        "",
    ]
    for chunk in chunks:
        lines.append(f"[{chunk.category}] {chunk.content}")
        lines.append(f"  — {chunk.title}")
        lines.append("")
    return "\n".join(lines)


# ── Ingestion ─────────────────────────────────────────────────────────────────
#
# Source files are Markdown with a small `key: value` frontmatter block
# (deliberately not YAML — avoids adding a parser dependency for a handful of
# flat string fields) followed by the document body. Each blank-line-separated
# paragraph becomes one chunk sharing that file's metadata. See
# backend/knowledge_base/README.md for the frontmatter contract and the
# verification status each source is expected to carry.

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)
_REQUIRED_FIELDS = ("source_id", "category", "title")


def _parse_source_file(path: Path) -> tuple[dict[str, str], list[str]]:
    raw = path.read_text(encoding="utf-8")
    match = _FRONTMATTER_RE.match(raw)
    if not match:
        raise ValueError(f"{path}: missing '--- ... ---' frontmatter block")
    meta_block, body = match.groups()

    meta: dict[str, str] = {}
    for line in meta_block.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip()

    missing = [f for f in _REQUIRED_FIELDS if not meta.get(f)]
    if missing:
        raise ValueError(f"{path}: frontmatter missing required field(s): {missing}")

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", body.strip()) if p.strip()]
    if not paragraphs:
        raise ValueError(f"{path}: no content paragraphs found after frontmatter")

    return meta, paragraphs


async def ingest_source(db: AsyncSession, path: Path) -> int:
    """(Re-)embed one source file. Replaces any existing chunks for its source_id."""
    meta, paragraphs = _parse_source_file(path)

    await db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.source_id == meta["source_id"]))

    vectors = await embed_texts(paragraphs)
    extra_meta = {k: v for k, v in meta.items() if k not in _REQUIRED_FIELDS}
    for i, (text, vec) in enumerate(zip(paragraphs, vectors)):
        db.add(KnowledgeChunk(
            source_id=meta["source_id"],
            category=meta["category"],
            title=meta["title"],
            content=text,
            meta={**extra_meta, "chunk_index": i},
            embedding=vec,
        ))
    await db.commit()
    return len(paragraphs)


async def ingest_directory(db: AsyncSession, directory: Path) -> dict[str, int]:
    """(Re-)embed every *.md source file in directory (except README.md)."""
    summary: dict[str, int] = {}
    for path in sorted(Path(directory).glob("*.md")):
        if path.name.lower() == "readme.md":
            continue
        meta, _ = _parse_source_file(path)
        count = await ingest_source(db, path)
        summary[meta["source_id"]] = count
    return summary
