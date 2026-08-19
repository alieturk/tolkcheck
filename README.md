# TolkCheck

AI-powered, reference-free deviation detection for interpreted IND asylum hearings (Turkish ↔ Dutch). Diagnostic support for the hoorambtenaar — it flags where the interpreter's rendering may have drifted semantically from what was actually said, without producing a verdict on the interpreter.

Built as an HBO-ICT graduation project (HvA). Core research question:

> Hoe kan een geautomatiseerde, referentieloze tool worden ontworpen en gerealiseerd die tijdens IND-asielgehoren semantische afwijkingen tussen de bronuiting en de tolkvertaling signaleert — als diagnostische ondersteuning voor de hoorambtenaar en zonder de tolk te beoordelen — binnen de privacy- en beveiligingskaders (AVG/BIO) van de IND?

The empirical scope is deliberately narrow: synthetic Turkish–Dutch test sessions, Turkish chosen as a hard case for its agglutinative morphology. See [`backend/evaluation/README.md`](backend/evaluation/README.md) for what's actually been measured, and its "Known limitations" section before drawing conclusions from any score this tool produces.

## How it works

A session goes through two phases, split by a manual checkpoint:

**Phase A** — upload → speaker diarization (pyannote.audio) → per-turn transcription (faster-whisper, `large-v3`) → `AWAITING_ROLE_CONFIRMATION`. The user tells the app which diarized speaker is the interpreter and which is the client.

**Phase B** (`resume_scoring`) — segments are grouped into same-speaker/same-language blocks, direction is classified (officer→client vs. client→officer), pairs are extracted, each pair is scored for semantic similarity (LaBSE), and Claude generates structured feedback — grounded, where a score is low enough to be flagged, with retrieved context from a small curated knowledge base (see [`backend/knowledge_base/README.md`](backend/knowledge_base/README.md)) rather than the model's own priors alone.

The two directions are **not** scored the same way, and this asymmetry is a known open question rather than a settled design: officer→client is scored cross-lingually and reference-free (direct LaBSE between Dutch and the client's language); client→officer routes through a Claude pseudo-translation to Dutch first, so it's not reference-free and folds a second model's error into the score. See the docstring on `resume_scoring` in `backend/app/pipeline.py` for the full reasoning and the (so far unfavourable) measurement behind it — this is exactly the kind of thing to read before trusting a c2o score.

## Tech stack

| Layer | Choice |
|---|---|
| Backend | FastAPI, SQLAlchemy (async), Alembic migrations |
| Database | PostgreSQL 16 + pgvector (RAG embeddings) |
| Task queue | ARQ (Redis-backed) |
| ASR | faster-whisper (`large-v3`, CPU/int8 by default) |
| Diarization | pyannote.audio (`speaker-diarization-3.1`, requires a HF token) |
| Semantic similarity | sentence-transformers / LaBSE |
| LLM feedback | Anthropic Claude |
| Frontend | Next.js 15, React 19, TypeScript, Tailwind |

## Quick start

Requires Docker Desktop. From the repo root:

```bash
cp backend/.env.example backend/.env
# then fill in HF_TOKEN, ANTHROPIC_API_KEY, and SECRET_KEY (openssl rand -hex 32)
```

```bash
docker compose up -d --build
docker compose exec backend uv run alembic upgrade head
docker compose exec backend uv run python -m app.cli ingest-knowledge knowledge_base
docker compose exec backend uv run python -m app.cli create-user someone@ind.nl --generate
```

Then open:

- **App** — http://localhost:3000 (log in with the account just created)
- **API docs** — http://localhost:8000/docs
- **Adminer** (DB browser) — http://localhost:8080 · server `db`, user `postgres`, password `postgres`, database `tolkcheck`

`--build` matters on a fresh clone or after a dependency change (backend/worker bake their venv in at image build time, in a volume that isn't automatically refreshed). If you're on a machine that ran this stack before pgvector was introduced, drop the old `postgres_data` volume rather than reusing it — see the comment on the `db` service in `docker-compose.yml` for why (Alpine→Debian collation mismatch, not just a version bump) and the exact commands.

There's no public signup route; accounts are provisioned via the CLI (`create-user`) by whoever operates the deployment.

## Configuration

All backend config is environment variables, validated by `app/config.py` (`Settings`, pydantic-settings). See `backend/.env.example` for the full list with explanations; the notable ones:

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | Postgres connection string (overridden inside Docker Compose to reach the `db` service) |
| `HF_TOKEN` | Required for pyannote diarization — also requires accepting the model license at https://hf.co/pyannote/speaker-diarization-3.1 with the same account |
| `ANTHROPIC_API_KEY`, `LLM_MODEL` | Claude feedback generation |
| `WHISPER_MODEL`, `WHISPER_DEVICE`, `WHISPER_COMPUTE_TYPE` | ASR model/hardware. Default is `large-v3`/`cpu`/`int8` — a deliberately conservative, not yet fully evidenced choice; see the long comment above `whisper_model` in `config.py` before switching to `turbo` |
| `SECRET_KEY` | Required, no default — app refuses to start without it (`openssl rand -hex 32`) |
| `COOKIE_SECURE` | Must be set `false` for on-prem HTTP-only deployments, or the login cookie won't persist |

## Using it

1. **Upload** a session: audio file, the client's source language (drives both Whisper's language hint and the direction-classification logic — this must match what's actually spoken, not default to Dutch), an optional IND case number, and an optional free-text glossary of names/places/case-specific terms (passed to Whisper as `initial_prompt` on every transcription call, to cut down on proper-noun mis-transcription being mistaken for a translation error).
2. **Confirm roles** once diarization/transcription finish — tell the app which speaker is the interpreter and which is the client.
3. **Review the evaluation** once scoring + feedback finish: per-pair semantic scores, structured issues (omission / addition / mistranslation / false-negative, each with severity), and narrative LLM feedback.

## Project structure

```
backend/
  app/
    routers/        auth, sessions, evaluations — FastAPI routes
    services/        diarization, transcription, alignment, scoring,
                      feedback (LLM), embeddings, retrieval (RAG)
    models/           SQLAlchemy models (session, evaluation, user, knowledge)
    pipeline.py       Phase A / Phase B orchestration, run by the ARQ worker
    worker.py         ARQ WorkerSettings + model pre-loading on startup
    cli.py            operator CLI — create-user, ingest-knowledge
  alembic/versions/    migrations
  knowledge_base/      RAG source corpus (see its own README)
  evaluation/           measured-evidence harness for DV2, not unit tests (see its own README)
  tests/                pytest suite — pytest.ini scopes runs to this dir only
frontend/
  app/                 Next.js routes: /, /login, /upload, /sessions/[id]
  lib/                 api.ts (backend client), types.ts
docker-compose.yml      frontend, backend, worker, redis, db (pgvector), adminer
```

## Testing

```bash
# unit tests — fast, all heavy models/APIs mocked
docker compose exec backend uv run pytest

# measured-evidence harness — real models, real weights, needs HF_TOKEN + ANTHROPIC_API_KEY
# see backend/evaluation/README.md before running; not part of CI
docker compose exec backend uv pip install -e '.[eval]'
docker compose exec backend uv run python evaluation/make_fixtures.py
docker compose exec backend uv run python evaluation/run_all.py
```

Frontend:

```bash
cd frontend
npm run lint
npm run type-check
```

## Known limitations (read before relying on any output)

- **No field validation.** All evaluation to date runs on synthetic TTS audio and LLM-authored labelled pairs, none of it reviewed by a native Turkish speaker or tested against a real IND hearing. See `backend/evaluation/README.md`'s provenance section.
- **The c2o (client→officer, legally decisive) scoring path is not reference-free** and its indirection through a Claude pseudo-translation has not been shown to improve score separation over scoring cross-lingually — see the `resume_scoring` docstring in `app/pipeline.py`.
- **Same-length meaning reversals (e.g. a flipped negation) are not reliably caught** by either scoring path in the current measurement — see `evaluation/results/` and the TODO in `app/services/feedback.py`.
- **The RAG knowledge base is a starter corpus**, not a finished bronnenlijst — five sources across three categories, no DV1/DV3 (legal/privacy) material, no adversarial examples. See `backend/knowledge_base/README.md`.
- Pre-existing CRLF/LF drift exists across much of the repo, unrelated to any feature work — expect a large `git diff` on files you haven't touched; it's a line-ending artifact, not a functional change.
