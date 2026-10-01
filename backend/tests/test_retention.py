"""Retention job (EIS-5): data older than retention_days is deleted, newer data
is kept, and a failed audio delete never loses track of the file.

The clock is injected (`now=`) instead of waiting 90 days. Requires a real
Postgres instance — see TEST_DATABASE_URL in conftest.py.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import func, select

from app.models.evaluation import Evaluation
from app.models.session import Session, SessionStatus
from app.services.retention import purge_expired

NOW = datetime(2026, 10, 1, 3, 0, tzinfo=timezone.utc)


@pytest.fixture
def uploads(tmp_path) -> Path:
    d = tmp_path / "uploads"
    d.mkdir()
    return d


@pytest.fixture
def add_session(db_session, make_user, uploads):
    owner = {}

    async def _add(age_days: float, status=SessionStatus.COMPLETED, with_audio=True,
                   with_eval=True) -> tuple[Session, Path]:
        if "user" not in owner:
            owner["user"], _ = await make_user()
        created = NOW - timedelta(days=age_days)
        s = Session(owner_id=owner["user"].id, filename="x.wav", status=status,
                    audio_path="", created_at=created)
        db_session.add(s)
        await db_session.flush()
        audio = uploads / f"{s.id}.wav"
        s.audio_path = str(audio)
        if with_audio:
            audio.write_bytes(b"RIFF")
        if with_eval:
            db_session.add(Evaluation(session_id=s.id, transcript=[{"text": "synthetic"}]))
        await db_session.commit()
        return s, audio

    return _add


async def _count(db, model) -> int:
    return (await db.execute(select(func.count()).select_from(model))).scalar_one()


class TestRetention:
    @pytest.mark.asyncio
    async def test_expired_session_evaluation_and_audio_are_deleted(self, db_session, add_session, uploads):
        old, old_audio = await add_session(age_days=91)
        new, new_audio = await add_session(age_days=89)

        result = await purge_expired(db_session, now=NOW, retention_days=90, upload_dir=uploads)

        assert result["sessions_deleted"] == 1
        assert result["audio_files_deleted"] == 1
        assert not old_audio.exists()
        assert new_audio.exists()
        remaining = (await db_session.execute(select(Session.id))).scalars().all()
        assert remaining == [new.id]
        # transcript went with the session (ON DELETE CASCADE)
        assert await _count(db_session, Evaluation) == 1

    @pytest.mark.asyncio
    async def test_abandoned_unfinished_session_is_also_purged(self, db_session, add_session, uploads):
        _, audio = await add_session(age_days=120, status=SessionStatus.AWAITING_ROLE_CONFIRMATION)

        result = await purge_expired(db_session, now=NOW, retention_days=90, upload_dir=uploads)

        assert result["sessions_deleted"] == 1
        assert not audio.exists()

    @pytest.mark.asyncio
    async def test_dry_run_deletes_nothing(self, db_session, add_session, uploads):
        _, audio = await add_session(age_days=91)

        result = await purge_expired(db_session, now=NOW, retention_days=90,
                                     upload_dir=uploads, dry_run=True)

        assert result["sessions_deleted"] == 1 and result["dry_run"]
        assert audio.exists()
        assert await _count(db_session, Session) == 1

    @pytest.mark.asyncio
    async def test_failed_audio_delete_keeps_the_row_for_retry(self, db_session, add_session, uploads):
        _, audio = await add_session(age_days=91)

        with patch.object(Path, "unlink", side_effect=PermissionError("locked")):
            result = await purge_expired(db_session, now=NOW, retention_days=90, upload_dir=uploads)

        assert result["audio_delete_failed"] == 1
        assert result["sessions_deleted"] == 0
        assert audio.exists()
        assert await _count(db_session, Session) == 1

    @pytest.mark.asyncio
    async def test_old_orphan_files_removed_recent_and_owned_kept(self, db_session, add_session, uploads):
        _, owned = await add_session(age_days=10)
        old_orphan = uploads / "crashed-upload.wav"
        new_orphan = uploads / "in-flight-upload.wav"
        for f in (old_orphan, new_orphan):
            f.write_bytes(b"RIFF")
        old_ts = (NOW - timedelta(days=100)).timestamp()
        os.utime(old_orphan, (old_ts, old_ts))
        new_ts = (NOW - timedelta(days=1)).timestamp()
        os.utime(new_orphan, (new_ts, new_ts))
        os.utime(owned, (old_ts, old_ts))  # old mtime, but a live session owns it

        result = await purge_expired(db_session, now=NOW, retention_days=90, upload_dir=uploads)

        assert result["orphan_files_deleted"] == 1
        assert not old_orphan.exists()
        assert new_orphan.exists()
        assert owned.exists()


def test_worker_schedules_retention_daily():
    from app.worker import WorkerSettings, purge_expired_sessions

    jobs = [j for j in WorkerSettings.cron_jobs if j.coroutine is purge_expired_sessions]
    assert len(jobs) == 1
    assert jobs[0].run_at_startup
