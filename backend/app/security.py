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

from app.audit import audit
from app.config import settings
from app.database import get_session as get_db
from app.models.user import User

AUTH_COOKIE_NAME = "tolkcheck_session"

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return _pwd_context.verify(plain, hashed)


_dummy_hash: str | None = None


def burn_password_check(plain: str) -> None:
    """Spend the same bcrypt time as a real check when there is nothing to
    check against (unknown, locked or inactive account), so response time
    does not reveal which accounts exist or are locked."""
    global _dummy_hash
    if _dummy_hash is None:
        _dummy_hash = _pwd_context.hash("timing-equaliser-not-a-password")
    _pwd_context.verify(plain, _dummy_hash)


class InvalidTokenError(Exception):
    """Raised when a JWT is missing, malformed, expired, or otherwise unusable."""


def create_access_token(subject: uuid.UUID, token_version: int = 0) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.access_token_expire_minutes
    )
    payload = {"sub": str(subject), "ver": token_version, "exp": expire}
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def decode_access_claims(token: str) -> tuple[uuid.UUID, int]:
    """Verify signature and expiry; return (user id, token version)."""
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    except JWTError as exc:
        raise InvalidTokenError(str(exc)) from exc

    sub = payload.get("sub")
    if sub is None:
        raise InvalidTokenError("Token missing 'sub' claim")
    try:
        user_id = uuid.UUID(sub)
    except ValueError as exc:
        raise InvalidTokenError("Token 'sub' claim is not a valid UUID") from exc

    ver = payload.get("ver")
    if not isinstance(ver, int):
        # Tokens issued before revocation existed carry no version: re-login.
        raise InvalidTokenError("Token missing 'ver' claim")
    return user_id, ver


def decode_access_token(token: str) -> uuid.UUID:
    return decode_access_claims(token)[0]


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
        user_id, token_version = decode_access_claims(token)
    except InvalidTokenError:
        audit("auth.rejected", request, reason="invalid_token", path=request.url.path)
        raise unauthorized

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        audit("auth.rejected", request, reason="inactive_or_unknown_user",
              user=user_id, path=request.url.path)
        raise unauthorized
    if token_version != user.token_version:
        audit("auth.rejected", request, reason="revoked_token", user=user_id,
              path=request.url.path)
        raise unauthorized

    return user
