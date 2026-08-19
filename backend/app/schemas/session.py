from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.session import SessionStatus


class SessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    filename: str
    audio_path: str
    language: str
    ind_case_id: str | None
    known_terms: str | None
    status: SessionStatus
    duration_seconds: float | None
    error_code: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime
