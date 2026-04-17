"""Two-phase AI pipeline orchestrator.

Phase A — run_pipeline (triggered on upload):
  transcribe -> diarise -> merge -> save transcript -> AWAITING_ROLE_CONFIRMATION

Phase B — resume_scoring (triggered after user confirms speaker roles):
  split by speaker -> LaBSE score -> LLM feedback -> save scores -> COMPLETED

Both phases update Session.status in the DB between each step so the
frontend stepper always reflects the current state.
"""
from __future__ import annotations

import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models.evaluation import Evaluation
from app.models.session import Session, SessionStatus
from app.services import diarization, feedback, scoring, transcription

# ── Error codes (maps to Dutch UI messages in the frontend) ──────────────────
ERR_UNSUPPORTED_FORMAT   = "UNSUPPORTED_FORMAT"
ERR_TRANSCRIPTION_FAILED = "TRANSCRIPTION_FAILED"
ERR_DIARISATION_FAILED   = "DIARISATION_FAILED"
ERR_SCORING_FAILED       = "SCORING_FAILED"
ERR_LLM_ERROR            = "LLM_ERROR"


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _get_session(db: AsyncSession, session_id: uuid.UUID) -> Session:
    result = await db.execute(select(Session).where(Session.id == session_id))
    session = result.scalar_one_or_none()
    if session is None:
        raise ValueError(f"Session {session_id} not found")
    return session


async def _set_status(
    db: AsyncSession,
    session: Session,
    new_status: SessionStatus,
) -> None:
    session.status = new_status
    await db.commit()


async def _set_failed(
    db: AsyncSession,
    session: Session,
    error_code: str,
    error_message: str,
) -> None:
    session.status = SessionStatus.FAILED
    session.error_code = error_code
    session.error_message = error_message
    await db.commit()


def _split_by_speaker(
    segments: list[dict],
    interpreter_speaker: str,
) -> tuple[list[str], list[str]]:
    """Return (interpreter_texts, client_texts) split by the confirmed speaker ID.

    Segments are paired positionally: interpreter segment i is scored against
    the nearest client segment. For now we split and truncate to the shorter list
    so score_segments always receives equal-length inputs.
    """
    interp = [s["text"] for s in segments if s.get("speaker") == interpreter_speaker]
    client = [s["text"] for s in segments if s.get("speaker") != interpreter_speaker]
    min_len = min(len(interp), len(client))
    return interp[:min_len], client[:min_len]


# ── Phase A ───────────────────────────────────────────────────────────────────

async def run_pipeline(session_id: str) -> None:
    """Phase A: transcribe + diarise, then pause for role confirmation."""
    sid = uuid.UUID(session_id)

    async with AsyncSessionLocal() as db:
        session = await _get_session(db, sid)
        audio_path = Path(session.audio_path)
        language = session.language

        try:
            # 1. Transcribe
            await _set_status(db, session, SessionStatus.TRANSCRIBING)
            try:
                transcript_data = await transcription.transcribe(audio_path, language)
            except Exception as exc:
                await _set_failed(db, session, ERR_TRANSCRIPTION_FAILED, str(exc))
                return

            # 2. Diarise
            await _set_status(db, session, SessionStatus.DIARISING)
            try:
                turns = await diarization.diarize(audio_path)
            except Exception as exc:
                await _set_failed(db, session, ERR_DIARISATION_FAILED, str(exc))
                return

            # 3. Merge transcript segments with speaker labels
            merged = diarization.merge_transcript_with_diarization(
                transcript_data["segments"], turns
            )

            # 4. Save transcript to Evaluation row; update session duration
            session.duration_seconds = transcript_data.get("duration")
            eval_row = Evaluation(session_id=sid, transcript=merged)
            db.add(eval_row)
            await _set_status(db, session, SessionStatus.AWAITING_ROLE_CONFIRMATION)

        except Exception as exc:
            await _set_failed(db, session, ERR_TRANSCRIPTION_FAILED, str(exc))


# ── Phase B ───────────────────────────────────────────────────────────────────

async def resume_scoring(session_id: str) -> None:
    """Phase B: score + LLM feedback after the user has confirmed speaker roles."""
    sid = uuid.UUID(session_id)

    async with AsyncSessionLocal() as db:
        session = await _get_session(db, sid)

        # Load the Evaluation row written in Phase A
        result = await db.execute(
            select(Evaluation).where(Evaluation.session_id == sid)
        )
        eval_row = result.scalar_one_or_none()
        if eval_row is None or eval_row.interpreter_speaker is None:
            await _set_failed(
                db, session,
                ERR_SCORING_FAILED,
                "Evaluation row missing or roles not confirmed",
            )
            return

        transcript: list[dict] = eval_row.transcript or []
        interpreter_speaker = eval_row.interpreter_speaker

        try:
            # 5. Score
            await _set_status(db, session, SessionStatus.SCORING)
            interp_texts, client_texts = _split_by_speaker(transcript, interpreter_speaker)

            if not interp_texts or not client_texts:
                await _set_failed(
                    db, session,
                    ERR_SCORING_FAILED,
                    "Not enough segments to score after speaker split",
                )
                return

            try:
                scores = await scoring.score_segments(client_texts, interp_texts)
            except Exception as exc:
                await _set_failed(db, session, ERR_SCORING_FAILED, str(exc))
                return

            agg = scoring.aggregate_scores(scores)
            # Map mean cosine similarity (0–1) to a 0–100 scale
            overall = round(agg["mean"] * 100, 1)
            eval_row.overall_score        = overall
            eval_row.accuracy_score       = overall        # same source until model-specific scoring
            eval_row.completeness_score   = round(min(len(interp_texts) / max(len(client_texts), 1), 1.0) * 100, 1)
            eval_row.terminology_score    = overall        # placeholder — specialised model TBD
            eval_row.fluency_score        = overall        # placeholder — specialised model TBD
            eval_row.semantic_similarity_scores = scores

            # 6. Generate LLM feedback
            await _set_status(db, session, SessionStatus.GENERATING)
            try:
                feedback_text = await feedback.generate_feedback(
                    {"segments": transcript}, scores
                )
            except Exception as exc:
                await _set_failed(db, session, ERR_LLM_ERROR, str(exc))
                return

            eval_row.llm_feedback = feedback_text
            await _set_status(db, session, SessionStatus.COMPLETED)

        except Exception as exc:
            await _set_failed(db, session, ERR_SCORING_FAILED, str(exc))
