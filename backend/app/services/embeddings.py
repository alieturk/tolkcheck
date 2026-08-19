"""Shared LaBSE sentence-embedding model — one instance for scoring and retrieval.

LaBSE was already the pipeline's cross-lingual embedding model (see
services/scoring.py's docstring). The retrieval module (services/retrieval.py)
reuses the exact same model and loading pattern instead of pulling in a second
embedding model, so the knowledge base lives in the same embedding space the
scoring pipeline already relies on for its similarity scores, and the process
only ever loads one ~1.8GB transformer.
"""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

_model: SentenceTransformer | None = None


def get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        _model = SentenceTransformer("LaBSE")
    return _model


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """Encode texts into LaBSE's 768-dim, L2-normalised embedding space."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _embed_sync, texts)


def _embed_sync(texts: list[str]) -> list[list[float]]:
    model = get_model()
    embeddings = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return embeddings.tolist()
