"""Auth infrastructure — password hashing, JWT issuance/verification, and the
`get_current_user` FastAPI dependency.

Token delivery is a cookie (httpOnly, SameSite=Lax), not an Authorization
header — see AUTH_COOKIE_NAME. This keeps the JWT out of JS-reachable
storage, which matters given the sensitivity of the data this app handles.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request, status
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_session as get_db
from app.models.user import User

AUTH_COOKIE_NAME = "tolkcheck_session"

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return _pwd_context.verify(plain, hashed)


class InvalidTokenError(Exception):
    """Raised when a JWT is missing, malformed, expired, or otherwise unusable."""


def create_access_token(subject: uuid.UUID) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.access_token_expire_minutes
    )
    payload = {"sub": str(subject), "exp": expire}
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def decode_access_token(token: str) -> uuid.UUID:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    except JWTError as exc:
        raise InvalidTokenError(str(exc)) from exc

    sub = payload.get("sub")
    if sub is None:
        raise InvalidTokenError("Token missing 'sub' claim")
    try:
        return uuid.UUID(sub)
    except ValueError as exc:
        raise InvalidTokenError("Token 'sub' claim is not a valid UUID") from exc


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    token = request.cookies.get(AUTH_COOKIE_NAME)
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
    )
    if not token:
        raise unauthorized

    try:
        user_id = decode_access_token(token)
    except InvalidTokenError:
        raise unauthorized

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise unauthorized

    return user
