"""LaBSE semantic similarity scoring (language-agnostic sentence embeddings).

LaBSE encodes sentences from any language into a shared embedding space,
making it ideal for comparing source (e.g. Arabic) with interpreted (Dutch) segments.
"""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

_model: SentenceTransformer | None = None


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        _model = SentenceTransformer("LaBSE")
    return _model


async def score_segments(
    source_segments: list[str],
    target_segments: list[str],
) -> list[float]:
    """Return per-segment cosine similarity scores (0.0–1.0)."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _score_sync, source_segments, target_segments)


def _score_sync(sources: list[str], targets: list[str]) -> list[float]:
    import numpy as np

    model = _get_model()
    src_emb = model.encode(sources, normalize_embeddings=True, show_progress_bar=False)
    tgt_emb = model.encode(targets, normalize_embeddings=True, show_progress_bar=False)
    # Cosine similarity = dot product of L2-normalised vectors
    scores: list[float] = np.sum(src_emb * tgt_emb, axis=1).tolist()
    return scores


def aggregate_scores(scores: list[float]) -> dict[str, float]:
    if not scores:
        return {"mean": 0.0, "min": 0.0, "max": 0.0}
    return {
        "mean": sum(scores) / len(scores),
        "min": min(scores),
        "max": max(scores),
    }
