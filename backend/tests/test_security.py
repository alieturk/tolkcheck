"""Unit tests for token issuance/verification in app.security.

Pure functions — no DB, no HTTP, no network.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from jose import jwt

from app.config import settings
from app.security import (
    InvalidTokenError,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


class TestPasswordHashing:
    def test_verify_correct_password(self):
        hashed = hash_password("correct horse battery staple")
        assert verify_password("correct horse battery staple", hashed)

    def test_verify_wrong_password(self):
        hashed = hash_password("correct horse battery staple")
        assert not verify_password("wrong password", hashed)

    def test_hash_is_not_plaintext(self):
        hashed = hash_password("secret")
        assert hashed != "secret"


class TestTokenRoundtrip:
    def test_encode_decode_roundtrip(self):
        user_id = uuid.uuid4()
        token = create_access_token(user_id)
        assert decode_access_token(token) == user_id

    def test_garbage_token_raises(self):
        with pytest.raises(InvalidTokenError):
            decode_access_token("not-a-real-token")

    def test_tampered_signature_raises(self):
        user_id = uuid.uuid4()
        token = create_access_token(user_id)
        tampered = token[:-1] + ("A" if token[-1] != "A" else "B")
        with pytest.raises(InvalidTokenError):
            decode_access_token(tampered)

    def test_expired_token_raises(self):
        # Hand-craft a token with an expiry in the past — create_access_token
        # always uses a positive expiry, so this bypasses it deliberately.
        user_id = uuid.uuid4()
        expired_payload = {
            "sub": str(user_id),
            "exp": datetime.now(timezone.utc) - timedelta(minutes=1),
        }
        expired_token = jwt.encode(expired_payload, settings.secret_key, algorithm=settings.algorithm)
        with pytest.raises(InvalidTokenError):
            decode_access_token(expired_token)

    def test_wrong_secret_raises(self):
        user_id = uuid.uuid4()
        payload = {
            "sub": str(user_id),
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        }
        wrong_secret_token = jwt.encode(payload, "a-different-secret", algorithm=settings.algorithm)
        with pytest.raises(InvalidTokenError):
            decode_access_token(wrong_secret_token)

    def test_missing_sub_claim_raises(self):
        payload = {"exp": datetime.now(timezone.utc) + timedelta(minutes=5)}
        token = jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)
        with pytest.raises(InvalidTokenError):
            decode_access_token(token)
