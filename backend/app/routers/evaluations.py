import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models.evaluation import Evaluation
from app.models.session import Session
from app.models.user import User
from app.schemas.evaluation import EvaluationOut
from app.security import get_current_user

router = APIRouter()


@router.get("/{session_id}", response_model=EvaluationOut)
async def get_evaluation(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Return the evaluation result for a completed session.

    Evaluation has no owner_id of its own — ownership is enforced by joining
    back to Session, whose owner_id was validated at upload time.
    """
    result = await db.execute(
        select(Evaluation)
        .join(Session, Evaluation.session_id == Session.id)
        .where(Evaluation.session_id == session_id, Session.owner_id == current_user.id)
    )
    evaluation = result.scalar_one_or_none()
    if not evaluation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Evaluation not yet available for this session.",
        )
    return evaluation
