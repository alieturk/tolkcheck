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


def _align_turns(
    segments: list[dict],
    interpreter_speaker: str,
    client_speaker: str,
) -> tuple[list[str], list[str]]:
    """Pair each interpreter turn with the nearest preceding client turn.

    Groups consecutive same-speaker segments into turns, then for every
    interpreter turn searches backwards for the most recent client turn.
    This matches consecutive interpretation's structure: client speaks,
    interpreter translates, rather than naively pairing by array index.
    """
    turns: list[dict] = []
    for seg in segments:
        if turns and turns[-1]["speaker"] == seg["speaker"]:
            turns[-1]["text"] += " " + seg["text"]
            turns[-1]["end"] = seg["end"]
        else:
            turns.append({
                "speaker": seg["speaker"],
                "start": seg["start"],
                "end": seg["end"],
                "text": seg["text"],
            })

    paired_interp: list[str] = []
    paired_client: list[str] = []
    for i, turn in enumerate(turns):
        if turn["speaker"] != interpreter_speaker:
            continue
        for j in range(i - 1, -1, -1):
            if turns[j]["speaker"] == client_speaker:
                paired_client.append(turns[j]["text"])
                paired_interp.append(turn["text"])
                break

    return paired_interp, paired_client


def _filter_hallucinations(segments: list[dict]) -> list[dict]:
    """Remove degenerate Whisper loops (same text repeated 3+ consecutive times)."""
    result: list[dict] = []
    for i, seg in enumerate(segments):
        if (i >= 2
                and seg["text"] == segments[i - 1]["text"]
                and seg["text"] == segments[i - 2]["text"]):
            continue
        result.append(seg)
    return result


# ── Phase A ───────────────────────────────────────────────────────────────────

async def run_pipeline(session_id: str) -> None:
    """Phase A: diarise → transcribe per turn → merge → AWAITING_ROLE_CONFIRMATION.

    Diarising first lets each speaker-turn chunk be transcribed independently,
    so Whisper detects language per chunk rather than locking to the dominant
    language of the whole file.
    """
    sid = uuid.UUID(session_id)

    async with AsyncSessionLocal() as db:
        session = await _get_session(db, sid)
        audio_path = Path(session.audio_path)
        language = session.language

        try:
            # 1. Diarise (language-agnostic — operates on raw audio signal)
            await _set_status(db, session, SessionStatus.DIARISING)
            try:
                turns = await diarization.diarize(audio_path)
            except Exception as exc:
                await _set_failed(db, session, ERR_DIARISATION_FAILED, str(exc))
                return

            # 2. Transcribe once per speaker (compact concat, not zero-masking)
            # Concatenate only actual speech chunks per speaker with 100ms silence
            # gaps, run Whisper once on the compact audio, remap timestamps back.
            await _set_status(db, session, SessionStatus.TRANSCRIBING)
            try:
                import torch
                import torchaudio
                waveform, sr = torchaudio.load(str(audio_path))
                speakers = sorted({t["speaker"] for t in turns})

                all_segments: list[dict] = []
                GAP_S = 0.1
                gap = torch.zeros(waveform.shape[0], int(GAP_S * sr))

                for speaker in speakers:
                    chunks = []
                    offsets = []  # (compact_start_s, original_start_s)
                    cursor = 0.0

                    for turn in turns:
                        if turn["speaker"] != speaker:
                            continue
                        s = int(turn["start"] * sr)
                        e = int(turn["end"] * sr)
                        chunk = waveform[:, s:e]
                        if chunk.shape[-1] < 800:
                            continue
                        offsets.append((cursor, turn["start"]))
                        chunks.append(chunk)
                        cursor += chunk.shape[-1] / sr + GAP_S

                    if not chunks:
                        continue

                    parts = []
                    for i, chunk in enumerate(chunks):
                        parts.append(chunk)
                        if i < len(chunks) - 1:
                            parts.append(gap)
                    compact = torch.cat(parts, dim=1)

                    segs = await transcription.transcribe_chunk(compact, sr, language)

                    for seg in segs:
                        for i, (c_start, o_start) in enumerate(offsets):
                            c_end = offsets[i + 1][0] if i + 1 < len(offsets) else cursor
                            if c_start <= seg["start"] < c_end:
                                shift = o_start - c_start
                                seg["start"] += shift
                                seg["end"]   += shift
                                break
                        seg["speaker"] = speaker

                    all_segments.extend(segs)
            except Exception as exc:
                await _set_failed(db, session, ERR_TRANSCRIPTION_FAILED, str(exc))
                return

            # 3. Sort by time, filter hallucinations, save
            all_segments.sort(key=lambda s: s["start"])
            merged = _filter_hallucinations(all_segments)

            session.duration_seconds = turns[-1]["end"] if turns else None
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
        if eval_row is None or eval_row.interpreter_speaker is None or eval_row.client_speaker is None:
            await _set_failed(
                db, session,
                ERR_SCORING_FAILED,
                "Evaluation row missing or roles not confirmed",
            )
            return

        transcript: list[dict] = eval_row.transcript or []
        interpreter_speaker = eval_row.interpreter_speaker
        client_speaker = eval_row.client_speaker

        try:
            # 5. Score
            await _set_status(db, session, SessionStatus.SCORING)
            interp_texts, client_texts = _align_turns(transcript, interpreter_speaker, client_speaker)

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
