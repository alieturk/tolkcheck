"""HTTP-level tests: login/logout/me, and ownership enforcement (the
IDOR-closing tests) across the sessions/evaluations routers.

Requires a real Postgres instance — see TEST_DATABASE_URL in conftest.py.
The ARQ enqueue call is mocked out so these tests don't need a live Redis.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient


def _mock_arq_pool():
    pool = AsyncMock()
    pool.enqueue_job = AsyncMock()
    pool.aclose = AsyncMock()
    return patch("app.routers.sessions._arq_pool", AsyncMock(return_value=pool))


async def _login(client: AsyncClient, email: str, password: str) -> None:
    res = await client.post("/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text


async def _upload_session(client: AsyncClient) -> str:
    res = await client.post(
        "/sessions",
        data={"language": "nl"},
        files={"audio": ("test.wav", b"\x00\x01\x02\x03", "audio/wav")},
    )
    assert res.status_code == 202, res.text
    return res.json()["session_id"]


# ── Login / logout / me ───────────────────────────────────────────────────────

class TestLogin:
    @pytest.mark.asyncio
    async def test_correct_credentials_sets_cookie(self, client, make_user):
        await make_user("alice@example.com", "hunter2")
        res = await client.post(
            "/auth/login", json={"email": "alice@example.com", "password": "hunter2"}
        )
        assert res.status_code == 200
        assert "tolkcheck_session" in res.cookies

    @pytest.mark.asyncio
    async def test_wrong_password_generic_401(self, client, make_user):
        await make_user("alice@example.com", "hunter2")
        res = await client.post(
            "/auth/login", json={"email": "alice@example.com", "password": "wrong"}
        )
        assert res.status_code == 401
        assert res.json()["detail"] == "Invalid credentials"

    @pytest.mark.asyncio
    async def test_nonexistent_email_same_generic_401(self, client, make_user):
        await make_user("alice@example.com", "hunter2")
        res = await client.post(
            "/auth/login", json={"email": "nobody@example.com", "password": "hunter2"}
        )
        assert res.status_code == 401
        assert res.json()["detail"] == "Invalid credentials"

    @pytest.mark.asyncio
    async def test_inactive_user_401(self, client, make_user, db_session):
        user, password = await make_user("alice@example.com", "hunter2")
        user.is_active = False
        await db_session.commit()

        res = await client.post(
            "/auth/login", json={"email": "alice@example.com", "password": password}
        )
        assert res.status_code == 401


class TestMeAndLogout:
    @pytest.mark.asyncio
    async def test_me_requires_auth(self, client):
        res = await client.get("/auth/me")
        assert res.status_code == 401

    @pytest.mark.asyncio
    async def test_me_returns_current_user(self, client, make_user):
        await make_user("alice@example.com", "hunter2")
        await _login(client, "alice@example.com", "hunter2")

        res = await client.get("/auth/me")
        assert res.status_code == 200
        assert res.json()["email"] == "alice@example.com"

    @pytest.mark.asyncio
    async def test_logout_clears_cookie(self, client, make_user):
        await make_user("alice@example.com", "hunter2")
        await _login(client, "alice@example.com", "hunter2")

        res = await client.post("/auth/logout")
        assert res.status_code == 200

        # A subsequent authenticated call should fail now that the cookie is cleared.
        me_res = await client.get("/auth/me")
        assert me_res.status_code == 401

    @pytest.mark.asyncio
    async def test_logout_works_without_a_session(self, client):
        res = await client.post("/auth/logout")
        assert res.status_code == 200


# ── Ownership enforcement (IDOR) ──────────────────────────────────────────────

class TestOwnershipEnforcement:
    @pytest.mark.asyncio
    async def test_sessions_require_auth(self, client):
        assert (await client.get("/sessions")).status_code == 401
        assert (await client.get("/sessions/00000000-0000-0000-0000-000000000000")).status_code == 401
        assert (await client.get("/evaluations/00000000-0000-0000-0000-000000000000")).status_code == 401

    @pytest.mark.asyncio
    async def test_owner_can_access_own_session(self, client, make_user):
        await make_user("alice@example.com", "hunter2")
        await _login(client, "alice@example.com", "hunter2")

        with _mock_arq_pool():
            session_id = await _upload_session(client)
            get_res = await client.get(f"/sessions/{session_id}")
            assert get_res.status_code == 200
            assert get_res.json()["id"] == session_id

    @pytest.mark.asyncio
    async def test_list_sessions_scoped_to_owner(self, client, make_user):
        await make_user("alice@example.com", "hunter2")
        await make_user("bob@example.com", "swordfish")

        await _login(client, "alice@example.com", "hunter2")
        with _mock_arq_pool():
            await _upload_session(client)

        await client.post("/auth/logout")
        await _login(client, "bob@example.com", "swordfish")
        list_res = await client.get("/sessions")
        assert list_res.status_code == 200
        assert list_res.json() == []

    @pytest.mark.asyncio
    async def test_non_owner_gets_404_not_403(self, client, make_user):
        """The core IDOR-closing behavior: a non-owner's request must be
        indistinguishable from a request for a session that doesn't exist."""
        await make_user("alice@example.com", "hunter2")
        await make_user("bob@example.com", "swordfish")

        await _login(client, "alice@example.com", "hunter2")
        with _mock_arq_pool():
            session_id = await _upload_session(client)
        await client.post("/auth/logout")

        await _login(client, "bob@example.com", "swordfish")

        get_res = await client.get(f"/sessions/{session_id}")
        assert get_res.status_code == 404

        with _mock_arq_pool():
            start_res = await client.post(f"/sessions/{session_id}/start")
        assert start_res.status_code == 404

        confirm_res = await client.post(
            f"/sessions/{session_id}/confirm-roles",
            json={"interpreter_speaker": "SPEAKER_00", "client_speaker": "SPEAKER_01"},
        )
        assert confirm_res.status_code == 404

        eval_res = await client.get(f"/evaluations/{session_id}")
        assert eval_res.status_code == 404

    @pytest.mark.asyncio
    async def test_owner_can_start_own_pending_session(self, client, make_user):
        await make_user("alice@example.com", "hunter2")
        await _login(client, "alice@example.com", "hunter2")

        with _mock_arq_pool():
            session_id = await _upload_session(client)
            start_res = await client.post(f"/sessions/{session_id}/start")
        assert start_res.status_code == 202
