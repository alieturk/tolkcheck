from __future__ import annotations

import uuid
from pathlib import Path

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_session
from app.models.evaluation import Evaluation
from app.models.session import Session, SessionStatus

router = APIRouter()

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

ALLOWED_CONTENT_TYPES = {
    "audio/mpeg",
    "audio/wav",
    "audio/x-wav",
    "audio/mp4",
    "audio/ogg",
    "audio/webm",
    "video/mp4",  # mp4 containers are often mis-typed by browsers
}


async def _arq_pool():
    return await create_pool(RedisSettings.from_dsn(settings.redis_url))


# ── Upload ─────────────────────────────────────────────────────────────────────

@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def create_session(
    audio: UploadFile = File(...),
    language: str = Form("nl"),
    case_id: str | None = Form(None),
    db: AsyncSession = Depends(get_session),
):
    """Upload an audio file and queue Phase A of the evaluation pipeline."""
    if audio.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported media type '{audio.content_type}'. Use mp3, wav, mp4, ogg, or webm.",
        )

    session_id = uuid.uuid4()
    suffix = Path(audio.filename or "audio").suffix or ".bin"
    audio_path = UPLOAD_DIR / f"{session_id}{suffix}"

    contents = await audio.read()
    audio_path.write_bytes(contents)

    session = Session(
        id=session_id,
        filename=audio.filename or "audio",
        audio_path=str(audio_path),
        language=language,
        ind_case_id=case_id,
        status=SessionStatus.PENDING,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)

    arq = await _arq_pool()
    await arq.enqueue_job("run_pipeline", str(session_id))
    await arq.aclose()

    return {"session_id": str(session_id), "status": session.status}


# ── List ───────────────────────────────────────────────────────────────────────

@router.get("")
async def list_sessions(
    db: AsyncSession = Depends(get_session),
    limit: int = 50,
    offset: int = 0,
):
    """Return sessions ordered by creation date descending (for the dashboard)."""
    result = await db.execute(
        select(Session)
        .order_by(Session.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return result.scalars().all()


# ── Get one ────────────────────────────────────────────────────────────────────

@router.get("/{session_id}")
async def get_session(session_id: uuid.UUID, db: AsyncSession = Depends(get_session)):
    """Return session metadata and pipeline status."""
    result = await db.execute(select(Session).where(Session.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    return session


# ── Confirm speaker roles (triggers Phase B) ──────────────────────────────────

class ConfirmRolesRequest(BaseModel):
    interpreter_speaker: str  # e.g. "SPEAKER_00"
    client_speaker: str       # e.g. "SPEAKER_01"


@router.post("/{session_id}/confirm-roles", status_code=status.HTTP_202_ACCEPTED)
async def confirm_roles(
    session_id: uuid.UUID,
    body: ConfirmRolesRequest,
    db: AsyncSession = Depends(get_session),
):
    """Save speaker role assignment and enqueue Phase B (scoring + LLM feedback)."""
    result = await db.execute(select(Session).where(Session.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    if session.status != SessionStatus.AWAITING_ROLE_CONFIRMATION:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Session is in status '{session.status}', not awaiting role confirmation.",
        )

    # Write speaker roles to the Evaluation row
    eval_result = await db.execute(
        select(Evaluation).where(Evaluation.session_id == session_id)
    )
    eval_row = eval_result.scalar_one_or_none()
    if eval_row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Evaluation record not found for this session.",
        )

    eval_row.interpreter_speaker = body.interpreter_speaker
    eval_row.client_speaker = body.client_speaker
    await db.commit()

    arq = await _arq_pool()
    await arq.enqueue_job("resume_scoring", str(session_id))
    await arq.aclose()

    return {"session_id": str(session_id), "status": SessionStatus.SCORING}
