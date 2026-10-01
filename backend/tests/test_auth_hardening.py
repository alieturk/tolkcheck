"""BIO2 5.17 / 5.18 / 8.15 hardening: lockout, token revocation, account
deactivation, password policy, audit trail, and no raw errors in the API.

Requires a real Postgres instance — see TEST_DATABASE_URL in conftest.py.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from jose import jwt

from app import cli
from app.config import settings
from app.schemas.session import SessionOut
from app.security import AUTH_COOKIE_NAME

EMAIL, PASSWORD = "officer@example.test", "correct horse battery"


async def _login(client: AsyncClient, password: str = PASSWORD, email: str = EMAIL):
    return await client.post("/auth/login", json={"email": email, "password": password})


@asynccontextmanager
async def _cli_db(db_session):
    """Point the CLI's AsyncSessionLocal at the test session."""
    @asynccontextmanager
    async def _session():
        yield db_session
    with patch.object(cli, "AsyncSessionLocal", _session):
        yield


class TestLockout:
    @pytest.mark.asyncio
    async def test_locks_after_max_failures_and_refuses_correct_password(self, client, make_user, db_session):
        user, _ = await make_user(EMAIL, PASSWORD)
        for _ in range(settings.login_max_failures):
            assert (await _login(client, "wrong")).status_code == 401

        res = await _login(client)  # right password, but locked
        assert res.status_code == 401
        assert res.json()["detail"] == "Invalid credentials"  # no hint that it is locked
        await db_session.refresh(user)
        assert user.locked_until is not None

    @pytest.mark.asyncio
    async def test_lock_expires(self, client, make_user, db_session):
        user, _ = await make_user(EMAIL, PASSWORD)
        user.locked_until = datetime.now(timezone.utc) - timedelta(seconds=1)
        await db_session.commit()
        assert (await _login(client)).status_code == 200

    @pytest.mark.asyncio
    async def test_success_resets_failure_count(self, client, make_user, db_session):
        user, _ = await make_user(EMAIL, PASSWORD)
        for _ in range(settings.login_max_failures - 1):
            await _login(client, "wrong")
        assert (await _login(client)).status_code == 200
        await db_session.refresh(user)
        assert user.failed_login_count == 0
        # the next mistakes start counting from zero again, so no lock yet
        for _ in range(settings.login_max_failures - 1):
            await _login(client, "wrong")
        assert (await _login(client)).status_code == 200


class TestRevocation:
    @pytest.mark.asyncio
    async def test_token_is_dead_after_logout(self, client, make_user):
        await make_user(EMAIL, PASSWORD)
        await _login(client)
        stolen = client.cookies.get(AUTH_COOKIE_NAME)

        await client.post("/auth/logout")
        client.cookies.set(AUTH_COOKIE_NAME, stolen)  # replay the old cookie
        assert (await client.get("/auth/me")).status_code == 401

    @pytest.mark.asyncio
    async def test_token_without_version_claim_is_rejected(self, client, make_user):
        user, _ = await make_user(EMAIL, PASSWORD)
        legacy = jwt.encode(
            {"sub": str(user.id), "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
            settings.secret_key, algorithm=settings.algorithm)
        client.cookies.set(AUTH_COOKIE_NAME, legacy)
        assert (await client.get("/auth/me")).status_code == 401

    @pytest.mark.asyncio
    async def test_deactivation_revokes_live_login(self, client, make_user, db_session):
        await make_user(EMAIL, PASSWORD)
        await _login(client)
        assert (await client.get("/auth/me")).status_code == 200

        async with _cli_db(db_session):
            await cli._set_active(EMAIL, False)
        assert (await client.get("/auth/me")).status_code == 401
        assert (await _login(client)).status_code == 401

        async with _cli_db(db_session):
            await cli._set_active(EMAIL, True)
        assert (await _login(client)).status_code == 200


class TestPasswordPolicy:
    @pytest.mark.asyncio
    async def test_short_password_rejected(self):
        with pytest.raises(SystemExit):
            await cli._create_user("x@example.test", "a" * (settings.password_min_length - 1))


class TestAuditTrail:
    @pytest.mark.asyncio
    async def test_login_events_are_audited_without_secrets(self, client, make_user, caplog):
        user, _ = await make_user(EMAIL, PASSWORD)
        caplog.set_level(logging.INFO, logger="audit")

        await _login(client, "wrong")
        await _login(client, email="nobody@example.test")
        await _login(client)

        lines = [r.getMessage() for r in caplog.records if r.name == "audit"]
        assert any(f"event=login.failure reason=bad_password user={user.id}" in m for m in lines)
        assert any("reason=unknown_user email_hash=" in m for m in lines)
        assert any(f"event=login.success user={user.id}" in m for m in lines)
        joined = "\n".join(lines)
        assert PASSWORD not in joined and "wrong" not in joined
        assert "nobody@example.test" not in joined and EMAIL not in joined

    @pytest.mark.asyncio
    async def test_foreign_session_probe_is_audited(self, client, make_user, caplog):
        await make_user(EMAIL, PASSWORD)
        await _login(client)
        caplog.set_level(logging.INFO, logger="audit")

        missing = "00000000-0000-0000-0000-000000000000"
        assert (await client.get(f"/sessions/{missing}")).status_code == 404
        assert any("event=session.not_found" in r.getMessage() and missing in r.getMessage()
                   for r in caplog.records if r.name == "audit")


def test_api_does_not_expose_raw_error_message():
    assert "error_message" not in SessionOut.model_fields
