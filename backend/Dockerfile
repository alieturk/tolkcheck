# ── Production Dockerfile ─────────────────────────────────
# One image for api, worker and the one-off migrate service in
# docker-compose.prod.yml. Runs as an unprivileged user (BIO2 5.18).
FROM python:3.12-slim

WORKDIR /app

# ffmpeg is required by faster-whisper / pyannote for audio decoding
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsox-dev \
    libsox-fmt-all \
    pkg-config \
    build-essential \
    && rm -rf /var/lib/apt/lists/*


RUN pip install uv

# Install exactly the locked versions (uv.lock), not whatever resolves today.
COPY pyproject.toml uv.lock ./
RUN uv sync --no-dev --frozen

COPY app/ ./app/
COPY alembic/ ./alembic/
COPY alembic.ini ./
COPY knowledge_base/ ./knowledge_base/

# Unprivileged runtime user. Writable paths: uploads (audio, deleted after
# processing) and the model cache (Whisper, LaBSE, pyannote weights).
RUN useradd --system --uid 10001 --home-dir /app --shell /usr/sbin/nologin tolkcheck \
    && mkdir -p /app/uploads /models \
    && chown tolkcheck:tolkcheck /app/uploads /models
ENV HF_HOME=/models \
    PATH="/app/.venv/bin:$PATH"
USER tolkcheck

EXPOSE 8000
# Called from the venv directly: `uv run` would try to sync as a user that
# cannot write the venv. --proxy-headers: behind the frontend/Caddy chain the
# client address comes from X-Forwarded-For (used in the audit log).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
