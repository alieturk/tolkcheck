"""ARQ worker — defines the task functions and WorkerSettings.

Start with:
  uv run arq app.worker.WorkerSettings

The worker shares the same DB + uploads volume as the backend service.
"""
from __future__ import annotations

import asyncio
import logging

from arq import ArqRedis
from arq.connections import RedisSettings
from arq.cron import cron

from app.config import settings
from app.logging_config import configure_logging
from app.pipeline import resume_scoring, run_pipeline

configure_logging(settings.log_level)
log = logging.getLogger(__name__)


async def startup(ctx: dict) -> None:
    """Pre-load heavy ML models so they are warm before the first job arrives.

    LaBSE and Whisper both take several minutes to initialise on CPU. Loading
    them here (no job timeout applies) avoids the risk of the first job timing
    out while the model is being loaded into memory.
    """
    loop = asyncio.get_event_loop()

    log.info("Pre-loading LaBSE model…")
    # LaBSE loading lives in embeddings.py (shared with RAG retrieval, see
    # app/services/retrieval.py); scoring.py just re-imports get_model() from
    # there rather than defining its own — import from the real source here
    # so this doesn't silently break again if scoring.py's import style changes.
    from app.services.embeddings import get_model as _get_labse
    await loop.run_in_executor(None, _get_labse)
    log.info("LaBSE ready.")

    log.info("Pre-loading Whisper model…")
    from app.services.transcription import _get_model as _get_whisper
    await loop.run_in_executor(None, _get_whisper)
    log.info("Whisper ready.")


async def shutdown(ctx: dict) -> None:
    """Called once when the worker process shuts down."""


async def purge_expired_sessions(ctx: dict) -> dict:
    """Daily retention run (EIS-5) — see app/services/retention.py."""
    from app.database import AsyncSessionLocal
    from app.services.retention import purge_expired

    async with AsyncSessionLocal() as db:
        return await purge_expired(db)


class WorkerSettings:
    functions = [run_pipeline, resume_scoring]
    # Daily at 03:00 (worker's clock), and once at startup so a day missed
    # while the worker was down is caught up rather than skipped.
    cron_jobs = [cron(purge_expired_sessions, hour=3, minute=0, run_at_startup=True)]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    # Retry failed jobs up to 3 times with exponential back-off
    max_tries = 3
    job_timeout = 60 * 60  # 1 hour — Whisper on CPU can be slow


# ── Helper used by the API to enqueue jobs ────────────────────────────────────

async def get_arq_pool() -> ArqRedis:
    """Return a connected ARQ Redis pool for use as a FastAPI dependency."""
    from arq import create_pool
    return await create_pool(RedisSettings.from_dsn(settings.redis_url))
