import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models.evaluation import Evaluation

router = APIRouter()


@router.get("/{session_id}")
async def get_evaluation(session_id: uuid.UUID, db: AsyncSession = Depends(get_session)):
    """Return the evaluation result for a completed session."""
    result = await db.execute(
        select(Evaluation).where(Evaluation.session_id == session_id)
    )
    evaluation = result.scalar_one_or_none()
    if not evaluation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Evaluation not yet available for this session.",
        )
    return evaluation
