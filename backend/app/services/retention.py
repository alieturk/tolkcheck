"""Retention (EIS-5, AVG art. 5(1)(e)): delete hearing data after a fixed term.

Process-and-delete (pipeline._delete_audio) removes the audio as soon as a
session finishes. This job is the backstop and the storage limit for the rest:

  1. Sessions uploaded more than `settings.retention_days` ago are deleted,
     whatever their status. Their evaluation row — transcript, aligned blocks,
     flags, LLM feedback — goes with them via the ON DELETE CASCADE foreign
     key. This also covers sessions abandoned before they finished, whose
     audio process-and-delete never reached.
  2. Their audio file is removed first if it is still on disk. If that fails,
     the session row is kept so the next run retries it, rather than losing
     the only record that the file exists.
  3. Audio files in the upload directory that belong to no session and are
     older than the cut-off are removed (an upload that crashed between
     writing the file and committing the row).

Runs daily from the ARQ worker (app/worker.py) and on demand via
`python -m app.cli purge-expired [--dry-run]`. `now` is injectable so the
behaviour can be tested and demonstrated without waiting 90 days.

Logs counts and session ids only — never filenames' contents or transcript text.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.session import Session
from app.routers.sessions import UPLOAD_DIR

log = logging.getLogger(__name__)


async def purge_expired(
    db: AsyncSession,
    *,
    now: datetime | None = None,
    retention_days: int | None = None,
    upload_dir: Path = UPLOAD_DIR,
    dry_run: bool = False,
) -> dict:
    """Delete everything past retention. Returns counts (and, for a dry run,
    what would have been deleted) so callers can report or assert on it."""
    now = now or datetime.now(timezone.utc)
    days = settings.retention_days if retention_days is None else retention_days
    cutoff = now - timedelta(days=days)

    rows = (await db.execute(
        select(Session.id, Session.audio_path).where(Session.created_at < cutoff)
    )).all()

    deletable: list[uuid.UUID] = []
    audio_deleted = 0
    audio_failed: list[uuid.UUID] = []
    for session_id, audio_path in rows:
        path = Path(audio_path)
        if dry_run:
            audio_deleted += path.exists()
            deletable.append(session_id)
            continue
        try:
            if path.exists():
                path.unlink()
                audio_deleted += 1
        except OSError as exc:
            log.error("retention  audio delete FAILED  session=%s  error=%s  — row kept, "
                      "retried next run", session_id, exc)
            audio_failed.append(session_id)
            continue
        deletable.append(session_id)

    if deletable and not dry_run:
        await db.execute(delete(Session).where(Session.id.in_(deletable)))
        await db.commit()

    # Orphans: files no session points to (compare by name; audio_path may be
    # relative or absolute depending on how the row was written).
    known = {Path(p).name for (p,) in (await db.execute(select(Session.audio_path))).all()}
    orphans_deleted = 0
    if upload_dir.exists():
        for f in upload_dir.iterdir():
            if not f.is_file() or f.name in known:
                continue
            if datetime.fromtimestamp(f.stat().st_mtime, timezone.utc) >= cutoff:
                continue
            if not dry_run:
                try:
                    f.unlink()
                except OSError as exc:
                    log.error("retention  orphan delete FAILED  file=%s  error=%s", f.name, exc)
                    continue
            orphans_deleted += 1

    result = {
        "cutoff": cutoff.isoformat(),
        "retention_days": days,
        "dry_run": dry_run,
        "sessions_deleted": len(deletable),
        "audio_files_deleted": audio_deleted,
        "audio_delete_failed": len(audio_failed),
        "orphan_files_deleted": orphans_deleted,
    }
    log.info("retention  %s  cutoff=%s  sessions=%d  audio=%d  failed=%d  orphans=%d",
             "DRY-RUN" if dry_run else "purged", result["cutoff"], result["sessions_deleted"],
             audio_deleted, len(audio_failed), orphans_deleted)
    return result
