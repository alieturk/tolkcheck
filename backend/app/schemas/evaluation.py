from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


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
    semantic_similarity_scores: list[Any] | None
    client_translations: list[Any] | None
    llm_feedback: str | None
    structured_issues: list[Any] | None
    created_at: datetime
    updated_at: datetime
