"""ARQ worker — defines the task functions and WorkerSettings.

Start with:
  uv run arq app.worker.WorkerSettings

The worker shares the same DB + uploads volume as the backend service.
"""
from __future__ import annotations

from arq import ArqRedis
from arq.connections import RedisSettings

from app.config import settings
from app.pipeline import resume_scoring, run_pipeline


async def startup(ctx: dict) -> None:
    """Called once when the worker process starts."""


async def shutdown(ctx: dict) -> None:
    """Called once when the worker process shuts down."""


class WorkerSettings:
    functions = [run_pipeline, resume_scoring]
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
