"""Shared pytest fixtures and helpers."""
from __future__ import annotations

import os

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base, get_session
from app.main import app
from app.models.user import User
from app.security import hash_password


def make_seg(
    speaker: str,
    text: str,
    start: float = 0.0,
    end: float = 1.0,
    language: str = "nl",
) -> dict:
    """Build a transcript segment dict — the canonical shape used throughout the pipeline."""
    return {"speaker": speaker, "text": text, "start": start, "end": end, "language": language}


# ── DB-backed API test infrastructure ────────────────────────────────────────
#
# These fixtures require a real Postgres instance (the app uses Postgres-only
# column types — JSONB, native UUID — so SQLite is not a viable substitute).
# Point TEST_DATABASE_URL at a disposable database; it defaults to the same
# DATABASE_URL the app would otherwise use, which is fine for local runs but
# NOT recommended for CI (it will create/drop tables against your dev DB).

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL") or os.environ.get(
    "DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/tolkcheck"
)


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def client(db_session: AsyncSession):
    async def _override_get_session():
        yield db_session

    app.dependency_overrides[get_session] = _override_get_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def make_user(db_session: AsyncSession):
    """Factory fixture: make_user() -> (User, plain_password)."""

    async def _make(email: str = "user@example.com", password: str = "correct horse") -> tuple[User, str]:
        user = User(email=email, hashed_password=hash_password(password))
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)
        return user, password

    yield _make
