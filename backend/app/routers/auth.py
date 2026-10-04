from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import audit, email_hash
from app.config import settings
from app.database import get_session as get_db
from app.models.user import User
from app.security import (
    AUTH_COOKIE_NAME,
    InvalidTokenError,
    burn_password_check,
    create_access_token,
    decode_access_claims,
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
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """Verify credentials and set the auth cookie.

    Never reveals whether the email exists, the account is disabled or the
    account is locked: same generic error, and the same bcrypt work, in every
    failure case. After settings.login_max_failures consecutive wrong
    passwords the account is locked for settings.login_lockout_minutes.
    """
    invalid = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid credentials",
    )
    now = datetime.now(timezone.utc)

    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()

    if user is None:
        burn_password_check(body.password)
        audit("login.failure", request, reason="unknown_user", email_hash=email_hash(body.email))
        raise invalid
    if user.locked_until is not None and user.locked_until > now:
        burn_password_check(body.password)
        audit("login.failure", request, reason="locked", user=user.id)
        raise invalid
    if not user.is_active:
        burn_password_check(body.password)
        audit("login.failure", request, reason="inactive", user=user.id)
        raise invalid

    if not verify_password(body.password, user.hashed_password):
        user.failed_login_count += 1
        if user.failed_login_count >= settings.login_max_failures:
            user.locked_until = now + timedelta(minutes=settings.login_lockout_minutes)
            user.failed_login_count = 0
            audit("account.locked", request, user=user.id,
                  minutes=settings.login_lockout_minutes)
        await db.commit()
        audit("login.failure", request, reason="bad_password", user=user.id)
        raise invalid

    user.failed_login_count = 0
    user.locked_until = None
    await db.commit()
    _set_auth_cookie(response, create_access_token(user.id, user.token_version))
    audit("login.success", request, user=user.id)
    return {"ok": True}


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """Clear the cookie and revoke the token server-side.

    Deliberately not gated by get_current_user — a stale/expired cookie must
    still be clearable. When the token is still valid, the user's
    token_version is bumped, which invalidates every token issued to that
    account so far (all devices), not just this cookie.
    """
    token = request.cookies.get(AUTH_COOKIE_NAME)
    if token:
        try:
            user_id, ver = decode_access_claims(token)
        except InvalidTokenError:
            pass
        else:
            user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
            if user is not None and user.token_version == ver:
                user.token_version += 1
                await db.commit()
                audit("logout", request, user=user.id)

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
