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
from app.services import (
    alignment,
    diarization,
    feedback,
    role_check,
    scoring,
    transcription,
)

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


def _pair_unassessable(pair: dict) -> bool:
    """True when either side of the pair has ASR the decoder itself distrusts.

    Both sides matter: a garbled interpreter block cannot be judged, and a garbled
    source block gives nothing valid to judge it against.
    """
    for key in ("interp_block", "source_block"):
        asr = pair.get(key, {}).get("asr")
        if asr and asr.get("unreliable"):
            return True
    return False


def _remap_compact_segment(
    seg: dict,
    spans: list[tuple[float, float, float, float]],
) -> None:
    """Map one segment's timestamps from compact-waveform time back to original time.

    ``spans`` holds ``(compact_start, compact_end, orig_start, orig_end)`` for each
    chunk that went into the compact waveform, in order.

    Whisper re-segments the concatenated audio on its own boundaries, which do not
    line up with the chunk boundaries. Attributing a segment by its start alone —
    and then shifting both endpoints by that chunk's offset without bounding them —
    lets a segment that straddles two chunks keep its compact-space duration and
    land anywhere in original time, including on top of another speaker's turn.
    That produced overlapping and zero-length turns downstream.

    So: pick the chunk this segment *overlaps most*, shift by that chunk's offset,
    then clamp into the chunk's original span. A remapped segment can therefore
    never escape the client turn it came from. Mutates ``seg`` in place.
    """
    if not spans:
        return

    best_i, best_overlap = None, 0.0
    for i, (c0, c1, _o0, _o1) in enumerate(spans):
        overlap = min(seg["end"], c1) - max(seg["start"], c0)
        if overlap > best_overlap:
            best_i, best_overlap = i, overlap

    if best_i is None:
        # Lies entirely inside an inter-chunk gap — attribute to the nearest chunk.
        best_i = min(
            range(len(spans)),
            key=lambda i: min(abs(seg["start"] - spans[i][0]), abs(seg["start"] - spans[i][1])),
        )
        log.warning("[B] remap  segment %.2f–%.2fs fell in a gap — nearest chunk=%d  %r",
                    seg["start"], seg["end"], best_i, seg["text"][:60].replace("\n", " "))
    elif best_overlap < (seg["end"] - seg["start"]) - 0.05:
        # Straddles a boundary: its text may mix two client turns. Cannot be split
        # without word-level timestamps, so it is attributed whole to the dominant
        # chunk — worth logging as a residual source of text/turn misattribution.
        log.warning("[B] remap  segment %.2f–%.2fs straddles chunks (overlap=%.2fs of %.2fs) "
                    "— attributed to chunk %d  %r",
                    seg["start"], seg["end"], best_overlap, seg["end"] - seg["start"],
                    best_i, seg["text"][:60].replace("\n", " "))

    c0, _c1, o0, o1 = spans[best_i]
    shift = o0 - c0
    start = min(max(seg["start"] + shift, o0), o1)
    end   = min(max(seg["end"]   + shift, start), o1)
    seg["start"], seg["end"] = start, end


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

                    segs = await transcription.transcribe_chunk(
                        chunk, sr, language, initial_prompt=session.known_terms
                    )

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
    """Phase B: score + LLM feedback after the user has confirmed speaker roles.

    ── The two directions are scored by DIFFERENT METHODS ────────────────────
    This asymmetry is deliberate but has not yet been validated. Be aware of it
    before drawing conclusions from either score.

    officer→client (o2c, "doorleidkwaliteit"):
        scoring.score_segments(officer_dutch, interpreter_source_lang)
        → genuinely reference-free, cross-lingual LaBSE: two different languages
          embedded into LaBSE's shared space and compared directly. No reference
          translation and no other model is involved.

    client→officer (c2o, "juridisch beslissend"):
        feedback.translate_to_dutch(client_source_lang)  ← Claude API call
        then scoring.score_segments(claude_dutch, interpreter_dutch)
        → NOT reference-free cross-lingual comparison. Claude produces a
          pseudo-reference translation and LaBSE then does a *monolingual*
          Dutch–Dutch similarity. Two models contribute to the number, and
          Claude's translation error is folded into the score indistinguishably
          from the interpreter's error.

    Why the legally decisive direction is the one using the indirect method is
    the awkward part. The working hypothesis is that LaBSE's cross-lingual
    alignment is weaker for Turkish–Dutch (morphologically rich, lower-resource
    on LaBSE's training mix) than its monolingual Dutch similarity, so routing
    through Dutch buys accuracy at the cost of method purity.

    THAT WAS A HYPOTHESIS, AND THE FIRST MEASUREMENT DOES NOT SUPPORT IT.
    evaluation/scoring_check.py runs the same labelled pairs down both paths.
    On its 20-pair set (see evaluation/results/ for the dated report) the Claude
    hop raises correct and deviant scores by nearly the same amount, so the gap
    between them — the only thing a threshold can act on — does not widen. It
    shifts the whole distribution upward instead of improving discrimination.

    So the current reading is that the c2o hop buys no separation while adding an
    API dependency, latency, cost, and a second error source on the legally
    decisive direction. The burden of proof is on keeping it. Do not treat that as
    settled either: n is 20 hand-written pairs that no native Turkish speaker has
    validated. Re-run scoring_check.py against better data before acting; if it
    holds, drop translate_to_dutch here and score c2o cross-lingually like o2c.

    Separately, and more seriously than the choice between the two paths: on that
    same set, 8 of 10 labelled deviations score above the 0.70 "semantically
    correct" cut-off on BOTH paths — including a flipped negation and a swapped
    date. Neither path detects same-length meaning reversals. See the report and
    the TODO(DV4) in services/feedback.py before relying on either score.

    Note _score_sync / translate_to_dutch are mocked in every test under tests/;
    the real numeric behaviour of this path is only exercised by
    evaluation/scoring_check.py.
    """
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

        # Detect client language from transcript segments (most common language among
        # client's utterances). Falls back to session.language only if no client segments
        # are found, then to "nl" as last resort.
        client_segments = [s for s in transcript if s.get("speaker") == client_speaker]
        if client_segments:
            lang_counts: dict[str, int] = {}
            for seg in client_segments:
                lang = seg.get("language", "?")
                lang_counts[lang] = lang_counts.get(lang, 0) + 1
            detected_lang = max(lang_counts, key=lang_counts.get)
            client_lang = detected_lang if detected_lang != "?" else (session.language or "nl")
            log.info("[B] detect_client_lang  from_transcript  distribution=%s  chosen=%s",
                     dict(lang_counts), client_lang)
        else:
            client_lang = session.language or "nl"
            log.warning("[B] detect_client_lang  no_client_segments  falling_back_to=%s",
                        client_lang)

        log.info("[B] session=%s  client=%s  interpreter=%s  client_lang=%s  transcript_segs=%d",
                 sid, client_speaker, interpreter_speaker, client_lang, len(transcript))

        try:
            # 5a. Re-transcribe client speaker with forced language (if non-Dutch)
            if client_lang != "nl" and Path(session.audio_path).exists():
                all_client_segs = [s for s in transcript if s["speaker"] == client_speaker]

                # Segments Phase A already detected as Dutch are almost certainly
                # the officer's speech misassigned to the client by diarization.
                # Forcing the client's language onto Dutch audio does not recover
                # Turkish — Whisper drifts into translating instead, which is where
                # the English lines in the transcript come from ("What was your job
                # in Turkey?"), and where Dutch gets mangled into pseudo-Turkish
                # ("Wanneer merkte" -> "Wanneye merkti"). Leave them on their Phase A
                # text: still misattributed, but at least not corrupted on top.
                client_segs_before = [s for s in all_client_segs if s.get("language") != "nl"]
                skipped_dutch      = [s for s in all_client_segs if s.get("language") == "nl"]

                log.info("[B] retranscribe  client_segs=%d  eligible=%d  skipped_dutch=%d  lang=%s",
                         len(all_client_segs), len(client_segs_before),
                         len(skipped_dutch), client_lang)
                for s in skipped_dutch:
                    log.warning("[B] retranscribe  SKIP_DUTCH  %.1f–%.1fs  %r  "
                                "— Dutch audio attributed to the client; "
                                "check diarization/role assignment",
                                s["start"], s["end"], s["text"][:70].replace(chr(10), " "))
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

                    # Per chunk: (compact_start, compact_end, orig_start, orig_end).
                    # orig_end is derived from the chunk's own sample count rather
                    # than seg["end"] so the compact and original spans have exactly
                    # equal duration — that makes the shift below lossless.
                    chunks: list = []
                    spans: list[tuple[float, float, float, float]] = []
                    cursor = 0.0
                    for seg in client_segs_before:
                        s_i = int(seg["start"] * sr)
                        e_i = int(seg["end"] * sr)
                        chunk = waveform[:, s_i:e_i]
                        if chunk.shape[-1] < 800:
                            continue
                        dur = chunk.shape[-1] / sr
                        spans.append((cursor, cursor + dur, seg["start"], seg["start"] + dur))
                        chunks.append(chunk)
                        cursor += dur + GAP_S

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

                        new_segs = await transcription.transcribe_chunk(
                            compact, sr, client_lang, initial_prompt=session.known_terms
                        )

                        for seg in new_segs:
                            _remap_compact_segment(seg, spans)
                            seg["speaker"] = client_speaker

                        log.info("[B] retranscribe  new_segs=%d", len(new_segs))
                        for s in new_segs:
                            log.debug("[B] retranscribe  AFTER   %.1f–%.1fs  lang=%-4s  %r",
                                      s["start"], s["end"], s.get("language", "?"),
                                      s["text"][:80].replace("\n", " "))

                        non_client = [s for s in transcript if s["speaker"] != client_speaker]
                        # skipped_dutch keeps its Phase A text — it is client-attributed
                        # but was never re-transcribed, so it must be added back by hand.
                        transcript = sorted(non_client + skipped_dutch + new_segs,
                                            key=lambda s: s["start"])
                        transcript = _filter_hallucinations(transcript)
                        eval_row.transcript = transcript
                    else:
                        log.warning("[B] retranscribe  SKIPPED — no usable client audio chunks")
                except Exception as exc:
                    log.warning("[B] retranscribe  FAILED (%s) — keeping Phase A transcript", exc)

            # 4b. Check the confirmed roles against the languages actually detected.
            # Runs on the post-re-transcription transcript and before any scoring, so
            # a hearing whose speakers were mixed up is recorded as such rather than
            # scored as if nothing were wrong. Reports only — see role_check for why
            # it does not reassign turns.
            roles = role_check.check_roles(
                transcript, interpreter_speaker, client_speaker, client_lang
            )
            eval_row.role_warnings = roles
            if not roles["ok"]:
                log.warning("[B] role_check  %d warning(s) — scores from this session "
                            "should be read with the speaker assignment in mind",
                            len(roles["warnings"]))

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

            # 5b. Translate client utterances to Dutch for Dutch↔Dutch c2o scoring.
            # This is the pseudo-reference hop described in this function's docstring —
            # it makes c2o scoring monolingual and NOT reference-free. Note the
            # `except` below silently falls back to scoring the untranslated source
            # cross-lingually, so a failed API call switches c2o to the o2c method
            # mid-session and the stored score is no longer method-comparable.
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

            # Mark pairs whose text Whisper itself decoded badly. A block flagged
            # here produced nonsense — a hallucinated language, a repetition loop,
            # text over silence — so its similarity score measures the decoder, not
            # the interpreter. Scoring those in with the rest turns an ASR failure
            # into a finding against the interpreter, which on a hearing transcript
            # is a conclusion nobody should be drawing from this number.
            for pair in c2o_pairs:
                pair["unassessable"] = _pair_unassessable(pair)
            for pair in o2c_pairs:
                pair["unassessable"] = _pair_unassessable(pair)

            assessable = [sc for sc, pair in zip(c2o_scores, c2o_pairs)
                          if not pair["unassessable"]]
            excluded = len(c2o_scores) - len(assessable)
            if excluded:
                log.warning("[B] scoring  %d of %d c2o pairs excluded from the aggregate "
                            "(unreliable ASR)", excluded, len(c2o_scores))
                for pair, sc in zip(c2o_pairs, c2o_scores):
                    if pair["unassessable"]:
                        asr = pair["interp_block"].get("asr") or {}
                        log.warning("[B] scoring  EXCLUDED c2o[%d]  score=%.3f  reasons=%s  %r",
                                    pair["pair_index"], sc, asr.get("reasons"),
                                    pair["interp_block"]["text"][:60].replace(chr(10), " "))

            if assessable:
                agg = scoring.aggregate_scores(assessable)
                overall = round(agg["mean"] * 100, 1)
                log.info("[B] c2o_scores  mean=%.3f  min=%.3f  max=%.3f  overall=%.1f/100  "
                         "(n=%d assessable, %d excluded)",
                         agg["mean"], agg["min"], agg["max"], overall, len(assessable), excluded)
            else:
                # Every pair was unreliable: report no score rather than a made-up one.
                overall = None
                log.error("[B] c2o_scores  no assessable pairs — overall score withheld")

            eval_row.overall_score        = overall
            eval_row.accuracy_score       = overall
            # Word counts over assessable pairs only — garbled text has a word count
            # but carries no content, so counting it inflates completeness.
            ok_idx = [i for i, pair in enumerate(c2o_pairs) if not pair["unassessable"]]
            total_src_words    = sum(len(scoring_texts[i].split())    for i in ok_idx)
            total_interp_words = sum(len(c2o_interp_texts[i].split()) for i in ok_idx)
            eval_row.completeness_score = (
                round(min(total_interp_words / total_src_words, 1.0) * 100, 1)
                if total_src_words else None
            )
            eval_row.terminology_score    = overall
            eval_row.fluency_score        = overall
            eval_row.semantic_similarity_scores = c2o_scores
            eval_row.aligned_blocks = blocks

            # 6. Generate LLM feedback (grounded with knowledge-base context — see
            # app/services/retrieval.py; passing db lets generate_feedback pull
            # relevant background material for pairs the score already flags as
            # uncertain or wrong)
            await _set_status(db, session, SessionStatus.GENERATING)
            log.info("[B] llm_feedback  requesting…")
            try:
                feedback_result = await feedback.generate_feedback(
                    c2o_pairs=c2o_pairs,
                    c2o_scores=c2o_scores,
                    o2c_pairs=o2c_pairs,
                    o2c_scores=o2c_scores,
                    db=db,
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
