from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_session as get_db
from app.models.user import User
from app.security import (
    AUTH_COOKIE_NAME,
    create_access_token,
    get_current_user,
    verify_password,
)

router = APIRouter()


class LoginRequest(BaseModel):
    email: str
    password: str


class MeOut(BaseModel):
    id: str
    email: str


def _set_auth_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=AUTH_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=settings.access_token_expire_minutes * 60,
        path="/",
    )


@router.post("/login")
async def login(
    body: LoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """Verify credentials and set the auth cookie. Never reveals whether the
    email exists — same generic error for unknown email vs. wrong password vs.
    a disabled account."""
    invalid = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid credentials",
    )

    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active or not verify_password(body.password, user.hashed_password):
        raise invalid

    token = create_access_token(user.id)
    _set_auth_cookie(response, token)
    return {"ok": True}


@router.post("/logout")
async def logout(response: Response):
    """Clears the auth cookie. Deliberately not gated by get_current_user —
    a stale/expired cookie must still be clearable."""
    response.delete_cookie(
        key=AUTH_COOKIE_NAME,
        path="/",
        samesite="lax",
        secure=settings.cookie_secure,
    )
    return {"ok": True}


@router.get("/me", response_model=MeOut)
async def me(current_user: User = Depends(get_current_user)):
    return MeOut(id=str(current_user.id), email=current_user.email)
