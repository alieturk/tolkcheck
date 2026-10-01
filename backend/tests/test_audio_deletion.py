"""Process-and-delete (EIS-5): the uploaded audio is removed once a session
reaches a terminal status, and no per-session score is exposed (EIS-2).

Requires a real Postgres instance — see TEST_DATABASE_URL in conftest.py.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import patch

import pytest

from app import pipeline
from app.models.session import Session, SessionStatus
from app.schemas.evaluation import EvaluationOut


@pytest.fixture
def make_session(db_session, make_user, tmp_path):
    async def _make(with_file: bool = True) -> tuple[Session, Path]:
        user, _ = await make_user()
        audio = tmp_path / "hearing.wav"
        if with_file:
            audio.write_bytes(b"RIFF....WAVE")
        session = Session(owner_id=user.id, filename="hearing.wav",
                          audio_path=str(audio), status=SessionStatus.PENDING)
        db_session.add(session)
        await db_session.commit()
        await db_session.refresh(session)
        return session, audio

    return _make


class TestDeleteOnTerminalStatus:
    @pytest.mark.asyncio
    async def test_failed_session_deletes_audio(self, db_session, make_session):
        session, audio = await make_session()

        await pipeline._set_failed(db_session, session, "TRANSCRIPTION_FAILED", "boom")

        assert not audio.exists()
        await db_session.refresh(session)
        assert session.status == SessionStatus.FAILED
        assert session.audio_deleted_at is not None

    @pytest.mark.asyncio
    async def test_already_missing_file_still_recorded_as_deleted(self, db_session, make_session):
        session, audio = await make_session(with_file=False)

        await pipeline._delete_audio(db_session, session)

        assert not audio.exists()
        assert session.audio_deleted_at is not None

    @pytest.mark.asyncio
    async def test_failed_delete_does_not_raise_and_stays_findable(self, db_session, make_session):
        session, audio = await make_session()

        with patch.object(Path, "unlink", side_effect=PermissionError("locked")):
            await pipeline._delete_audio(db_session, session)

        assert audio.exists()
        assert session.audio_deleted_at is None

    @pytest.mark.asyncio
    async def test_resume_scoring_failure_path_deletes_audio(self, db_session, make_session):
        """Real entry point: Phase B without an Evaluation row fails early."""
        session, audio = await make_session()

        @asynccontextmanager
        async def _use_test_session():
            yield db_session

        with patch.object(pipeline, "AsyncSessionLocal", _use_test_session):
            await pipeline.resume_scoring({}, str(session.id))

        assert not audio.exists()
        await db_session.refresh(session)
        assert session.status == SessionStatus.FAILED
        assert session.audio_deleted_at is not None


class TestNoSessionScore:
    def test_evaluation_api_exposes_only_per_pair_scores(self):
        score_fields = {f for f in EvaluationOut.model_fields if "score" in f}
        assert score_fields == {"semantic_similarity_scores"}
