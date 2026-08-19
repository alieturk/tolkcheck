"""Two-phase AI pipeline orchestrator.

Phase A — run_pipeline (triggered on upload):
  transcribe -> diarise -> merge -> save transcript -> AWAITING_ROLE_CONFIRMATION

Phase B — resume_scoring (triggered after user confirms speaker roles):
  split by speaker -> LaBSE score -> LLM feedback -> save scores -> COMPLETED

Both phases update Session.status in the DB between each step so the
frontend stepper always reflects the current state.
"""
from __future__ import annotations

import logging
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models.evaluation import Evaluation
from app.models.session import Session, SessionStatus
from app.services import alignment, diarization, feedback, scoring, transcription

log = logging.getLogger(__name__)

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

async def run_pipeline(ctx: dict, session_id: str) -> None:
    """Phase A: diarise → transcribe per turn → merge → AWAITING_ROLE_CONFIRMATION.

    Diarising first lets each speaker-turn chunk be transcribed independently,
    so Whisper detects language per chunk rather than locking to the dominant
    language of the whole file.
    """
    sid = uuid.UUID(session_id)

    async with AsyncSessionLocal() as db:
        session = await _get_session(db, sid)
        audio_path = Path(session.audio_path)
        # Always use language=None so Whisper auto-detects each speaker's language
        # independently. The session.language field is metadata only — passing it
        # to Whisper would force every speaker (incl. the Dutch IND officer) to be
        # decoded as the client's source language.
        language = None

        try:
            log.info("[A] session=%s  file=%s  source_lang=%s",
                     sid, audio_path.name, session.language)

            # 1. Diarise (language-agnostic — operates on raw audio signal)
            await _set_status(db, session, SessionStatus.DIARISING)
            try:
                # IND hearings always have exactly 3 parties (officer, interpreter, client).
                # Passing num_speakers prevents pyannote from splitting one person's voice
                # across multiple clusters when it is uncertain.
                turns = await diarization.diarize(audio_path, num_speakers=3)
            except Exception as exc:
                await _set_failed(db, session, ERR_DIARISATION_FAILED, str(exc))
                return

            # Log diarization summary: turns per speaker and their time spans
            speaker_turns: dict[str, list[dict]] = {}
            for t in turns:
                speaker_turns.setdefault(t["speaker"], []).append(t)
            for spk, spk_turns in sorted(speaker_turns.items()):
                spans = " ".join(
                    f"{t['start']:.1f}–{t['end']:.1f}s" for t in spk_turns
                )
                log.info("[A] diarization  speaker=%-12s  turns=%d  spans=[%s]",
                         spk, len(spk_turns), spans)

            # 2. Transcribe each diarization turn individually.
            # Processing per turn (not per speaker) gives Whisper its own language
            # detection window for every utterance. This is critical for the interpreter
            # who speaks both Dutch and the client's language: a compact-per-speaker
            # approach locks Whisper to the dominant language (Dutch) and produces
            # garbled hallucinations for the minority-language relay turns.
            await _set_status(db, session, SessionStatus.TRANSCRIBING)
            try:
                import torchaudio
                waveform, sr = torchaudio.load(str(audio_path))
                all_segments: list[dict] = []

                for turn in sorted(turns, key=lambda t: t["start"]):
                    s = int(turn["start"] * sr)
                    e = int(turn["end"] * sr)
                    chunk = waveform[:, s:e]
                    if chunk.shape[-1] < 800:  # skip slivers < ~50 ms
                        log.debug("[A] turn_skip  speaker=%-12s  %.2f–%.2fs  (too short)",
                                  turn["speaker"], turn["start"], turn["end"])
                        continue

                    segs = await transcription.transcribe_chunk(chunk, sr, language)

                    for seg in segs:
                        seg["start"] += turn["start"]
                        seg["end"]   += turn["start"]
                        seg["speaker"] = turn["speaker"]
                        log.debug("[A] segment  speaker=%-12s  lang=%-4s  %.1f–%.1fs  %r",
                                  turn["speaker"], seg.get("language", "?"),
                                  seg["start"], seg["end"],
                                  seg["text"][:80].replace("\n", " "))

                    if segs:
                        log.info("[A] turn  speaker=%-12s  %.1f–%.1fs  detected=%s  segs=%d",
                                 turn["speaker"], turn["start"], turn["end"],
                                 segs[0].get("language", "?"), len(segs))

                    all_segments.extend(segs)
            except Exception as exc:
                await _set_failed(db, session, ERR_TRANSCRIPTION_FAILED, str(exc))
                return

            # 3. Sort by time, filter hallucinations, save
            all_segments.sort(key=lambda s: s["start"])

            # Language distribution per speaker — key signal for diarization confusion:
            # if an expected-Dutch speaker shows >20% non-Dutch segments, pyannote
            # likely swapped the interpreter's Turkish voice with the client's.
            from collections import defaultdict
            lang_by_speaker: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
            for seg in all_segments:
                lang_by_speaker[seg["speaker"]][seg.get("language", "?")] += 1
            for spk, langs in sorted(lang_by_speaker.items()):
                log.info("[A] lang_dist  speaker=%-12s  langs=%s", spk, dict(langs))

            before_filter = len(all_segments)
            merged = _filter_hallucinations(all_segments)
            log.info("[A] filter_hallucinations  before=%d  after=%d  removed=%d",
                     before_filter, len(merged), before_filter - len(merged))

            session.duration_seconds = turns[-1]["end"] if turns else None
            eval_row = Evaluation(session_id=sid, transcript=merged)
            db.add(eval_row)
            log.info("[A] DONE  total_segments=%d  duration=%.1fs → AWAITING_ROLE_CONFIRMATION",
                     len(merged), session.duration_seconds or 0)
            await _set_status(db, session, SessionStatus.AWAITING_ROLE_CONFIRMATION)

        except Exception as exc:
            await _set_failed(db, session, ERR_TRANSCRIPTION_FAILED, str(exc))


# ── Phase B ───────────────────────────────────────────────────────────────────

async def resume_scoring(ctx: dict, session_id: str) -> None:
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
        client_lang: str = session.language or "nl"

        log.info("[B] session=%s  client=%s  interpreter=%s  client_lang=%s  transcript_segs=%d",
                 sid, client_speaker, interpreter_speaker, client_lang, len(transcript))

        try:
            # 5a. Re-transcribe client speaker with forced language (if non-Dutch)
            if client_lang != "nl" and Path(session.audio_path).exists():
                client_segs_before = [s for s in transcript if s["speaker"] == client_speaker]
                log.info("[B] retranscribe  client_segs_before=%d  lang=%s",
                         len(client_segs_before), client_lang)
                for s in client_segs_before:
                    log.debug("[B] retranscribe  BEFORE  %.1f–%.1fs  lang=%-4s  %r",
                              s["start"], s["end"], s.get("language", "?"),
                              s["text"][:80].replace("\n", " "))
                try:
                    import torch
                    import torchaudio
                    waveform, sr = torchaudio.load(str(session.audio_path))
                    GAP_S = 0.1
                    gap = torch.zeros(waveform.shape[0], int(GAP_S * sr))

                    chunks: list = []
                    offsets: list = []
                    cursor = 0.0
                    for seg in client_segs_before:
                        s_i = int(seg["start"] * sr)
                        e_i = int(seg["end"] * sr)
                        chunk = waveform[:, s_i:e_i]
                        if chunk.shape[-1] < 800:
                            continue
                        offsets.append((cursor, seg["start"]))
                        chunks.append(chunk)
                        cursor += chunk.shape[-1] / sr + GAP_S

                    if chunks:
                        parts = []
                        for i, chunk in enumerate(chunks):
                            parts.append(chunk)
                            if i < len(chunks) - 1:
                                parts.append(gap)
                        compact = torch.cat(parts, dim=1)
                        compact_dur = compact.shape[-1] / sr
                        log.info("[B] retranscribe  chunks=%d  compact=%.1fs  forced_lang=%s",
                                 len(chunks), compact_dur, client_lang)

                        new_segs = await transcription.transcribe_chunk(compact, sr, client_lang)

                        for seg in new_segs:
                            for i, (c_start, o_start) in enumerate(offsets):
                                c_end = offsets[i + 1][0] if i + 1 < len(offsets) else cursor
                                if c_start <= seg["start"] < c_end:
                                    shift = o_start - c_start
                                    seg["start"] += shift
                                    seg["end"]   += shift
                                    break
                            seg["speaker"] = client_speaker

                        log.info("[B] retranscribe  new_segs=%d", len(new_segs))
                        for s in new_segs:
                            log.debug("[B] retranscribe  AFTER   %.1f–%.1fs  lang=%-4s  %r",
                                      s["start"], s["end"], s.get("language", "?"),
                                      s["text"][:80].replace("\n", " "))

                        non_client = [s for s in transcript if s["speaker"] != client_speaker]
                        transcript = sorted(non_client + new_segs, key=lambda s: s["start"])
                        transcript = _filter_hallucinations(transcript)
                        eval_row.transcript = transcript
                    else:
                        log.warning("[B] retranscribe  SKIPPED — no usable client audio chunks")
                except Exception as exc:
                    log.warning("[B] retranscribe  FAILED (%s) — keeping Phase A transcript", exc)

            # 5. Build speaker blocks, classify interpreter direction, extract pairs
            await _set_status(db, session, SessionStatus.SCORING)
            blocks = alignment.build_blocks(transcript, interpreter_speaker, client_speaker)
            alignment.classify_directions(blocks, client_lang)
            c2o_pairs, o2c_pairs = alignment.extract_pairs(blocks)

            log.info("[B] blocks  total=%d  c2o_pairs=%d  o2c_pairs=%d",
                     len(blocks), len(c2o_pairs), len(o2c_pairs))

            if not c2o_pairs:
                await _set_failed(
                    db, session,
                    ERR_SCORING_FAILED,
                    "No client→officer pairs found after block alignment",
                )
                return

            c2o_client_texts = [p["source_block"]["text"] for p in c2o_pairs]
            c2o_interp_texts  = [p["interp_block"]["text"]  for p in c2o_pairs]
            o2c_officer_texts = [p["source_block"]["text"] for p in o2c_pairs]
            o2c_interp_texts  = [p["interp_block"]["text"]  for p in o2c_pairs]

            # 5b. Translate client utterances to Dutch for Dutch↔Dutch c2o scoring
            scoring_texts = c2o_client_texts
            if client_lang != "nl":
                log.info("[B] translate  %d texts from %s → nl", len(c2o_client_texts), client_lang)
                try:
                    scoring_texts = await feedback.translate_to_dutch(c2o_client_texts, client_lang)
                    eval_row.client_translations = scoring_texts
                    for i, (orig, trans) in enumerate(zip(c2o_client_texts, scoring_texts)):
                        log.info("[B] translate[%d]  %r → %r",
                                 i,
                                 orig[:60].replace("\n", " "),
                                 trans[:60].replace("\n", " "))
                except Exception as exc:
                    log.warning("[B] translate  FAILED (%s) — scoring with original text", exc)
                    scoring_texts = c2o_client_texts

            # Embed the Dutch scoring text in each pair dict so feedback can use it
            for pair, dutch in zip(c2o_pairs, scoring_texts):
                pair["scoring_text"] = dutch

            try:
                c2o_scores = await scoring.score_segments(scoring_texts, c2o_interp_texts)
                o2c_scores = (
                    await scoring.score_segments(o2c_officer_texts, o2c_interp_texts)
                    if o2c_pairs else []
                )
            except Exception as exc:
                await _set_failed(db, session, ERR_SCORING_FAILED, str(exc))
                return

            for i, sc in enumerate(c2o_scores):
                log.info("[B] c2o_score[%d]  %.4f  src=%r  tgt=%r",
                         i, sc,
                         scoring_texts[i][:60].replace("\n", " "),
                         c2o_interp_texts[i][:60].replace("\n", " "))
            for i, sc in enumerate(o2c_scores):
                log.info("[B] o2c_score[%d]  %.4f  src=%r  tgt=%r",
                         i, sc,
                         o2c_officer_texts[i][:60].replace("\n", " "),
                         o2c_interp_texts[i][:60].replace("\n", " "))

            agg = scoring.aggregate_scores(c2o_scores)
            overall = round(agg["mean"] * 100, 1)
            log.info("[B] c2o_scores  mean=%.3f  min=%.3f  max=%.3f  overall=%.1f/100",
                     agg["mean"], agg["min"], agg["max"], overall)

            eval_row.overall_score        = overall
            eval_row.accuracy_score       = overall
            total_src_words    = sum(len(t.split()) for t in scoring_texts)
            total_interp_words = sum(len(t.split()) for t in c2o_interp_texts)
            eval_row.completeness_score = round(
                min(total_interp_words / max(total_src_words, 1), 1.0) * 100, 1
            )
            eval_row.terminology_score    = overall
            eval_row.fluency_score        = overall
            eval_row.semantic_similarity_scores = c2o_scores
            eval_row.aligned_blocks = blocks

            # 6. Generate LLM feedback
            await _set_status(db, session, SessionStatus.GENERATING)
            log.info("[B] llm_feedback  requesting…")
            try:
                feedback_result = await feedback.generate_feedback(
                    c2o_pairs=c2o_pairs,
                    c2o_scores=c2o_scores,
                    o2c_pairs=o2c_pairs,
                    o2c_scores=o2c_scores,
                )
            except Exception as exc:
                await _set_failed(db, session, ERR_LLM_ERROR, str(exc))
                return

            issues_count = sum(
                len(p.get("issues", [])) for p in (feedback_result.get("structured_issues") or [])
            )
            log.info("[B] llm_feedback  pairs_reviewed=%d  issues_found=%d",
                     len(c2o_scores) + len(o2c_scores), issues_count)

            eval_row.llm_feedback      = feedback_result["overall_feedback"]
            eval_row.structured_issues = feedback_result["structured_issues"]
            log.info("[B] DONE  overall=%.1f  completeness=%.1f → COMPLETED",
                     overall, eval_row.completeness_score)
            await _set_status(db, session, SessionStatus.COMPLETED)

        except Exception as exc:
            log.exception("[B] UNHANDLED ERROR: %s", exc)
            await _set_failed(db, session, ERR_SCORING_FAILED, str(exc))
