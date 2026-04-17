import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
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


@router.post("/", status_code=status.HTTP_202_ACCEPTED)
async def create_session(
    audio: UploadFile = File(...),
    language: str = Form("nl"),
    case_id: str | None = Form(None),
    db: AsyncSession = Depends(get_session),
):
    """Upload an audio file and queue it for the evaluation pipeline."""
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

    # TODO: dispatch to a task queue (Celery / ARQ) for async pipeline execution
    # background_tasks.add_task(pipeline.run, session_id)

    return {"session_id": str(session_id), "status": session.status}


@router.get("/{session_id}")
async def get_session(session_id: uuid.UUID, db: AsyncSession = Depends(get_session)):
    """Return session metadata and pipeline status."""
    result = await db.execute(select(Session).where(Session.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    return session
