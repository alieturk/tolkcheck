from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator


class EvaluationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    session_id: uuid.UUID
    interpreter_speaker: str | None
    client_speaker: str | None
    overall_score: float | None
    accuracy_score: float | None
    completeness_score: float | None
    terminology_score: float | None
    fluency_score: float | None
    transcript: list[Any] | None
    # Speaker blocks with interpreter direction and pair linkage, as produced by
    # services/alignment.py. This is what the UI renders from: without it the
    # client would have to re-derive block merging and pairing from `transcript`,
    # and any divergence between the two implementations shows up as source text
    # paired with the wrong translation.
    aligned_blocks: list[Any] | None
    # Language distribution per speaker + any contradiction with the confirmed
    # role assignment (services/role_check.py). Surfaced in the UI so scores are
    # read alongside the evidence that the speakers may have been mixed up.
    role_warnings: dict[str, Any] | None
    semantic_similarity_scores: list[Any] | None
    client_translations: list[Any] | None
    llm_feedback: str | None
    structured_issues: list[Any] | None
    created_at: datetime
    updated_at: datetime

    @field_validator("aligned_blocks")
    @classmethod
    def _drop_block_segments(cls, blocks: list[Any] | None) -> list[Any] | None:
        """Strip each block's `segments` list from the response.

        Every raw segment is already sent in full via `transcript`; repeating
        them nested inside each block roughly doubles the payload for no gain
        (nothing in the UI reads them). Dropped here rather than at write time
        so the stored row keeps them for debugging.
        """
        if not blocks:
            return blocks
        return [
            {k: v for k, v in b.items() if k != "segments"} if isinstance(b, dict) else b
            for b in blocks
        ]
