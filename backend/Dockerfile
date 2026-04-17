# ── Production Dockerfile ─────────────────────────────────
FROM python:3.12-slim

WORKDIR /app

# ffmpeg is required by faster-whisper / pyannote for audio decoding
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

RUN pip install uv

COPY pyproject.toml ./
RUN uv sync --no-dev

COPY app/ ./app/

EXPOSE 8000
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
