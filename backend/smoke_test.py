"""Standalone AI stack smoke test — no database required.

Usage (inside the worker container):
    uv run python smoke_test.py /app/uploads/<filename> [--language nl]

Steps:
    1. Transcribe (Whisper large-v3)
    2. Diarise (whisperx / pyannote)
    3. Merge transcript with speaker turns
    4. Assign interpreter / client roles (first detected speaker = interpreter)
    5. Split segments by role
    6. Score (LaBSE cosine similarity)
    7. Generate LLM feedback (Anthropic)
"""
from __future__ import annotations

import argparse
import asyncio
import time
from pathlib import Path


def _fmt_time(seconds: float) -> str:
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m}:{s:02d}"


def _step(n: int, total: int, label: str) -> float:
    print(f"\n[{n}/{total}] {label}...", flush=True)
    return time.perf_counter()


def _done(t0: float) -> None:
    print(f"  done in {time.perf_counter() - t0:.1f}s", flush=True)


async def main(audio_path: Path, language: str) -> None:
    from app.services import diarization, feedback, scoring, transcription
    from app.pipeline import _split_by_speaker  # reuse existing helper

    total = 7

    # ── 1. Transcribe ──────────────────────────────────────────────────────────
    t0 = _step(1, total, "Transcribing (Whisper large-v3)")
    transcript_data = await transcription.transcribe(audio_path, language)
    _done(t0)
    segments = transcript_data["segments"]
    print(f"  language={transcript_data['language']}  "
          f"probability={transcript_data['language_probability']:.2f}  "
          f"duration={transcript_data.get('duration', 0):.1f}s  "
          f"segments={len(segments)}")

    # ── 2. Diarise ─────────────────────────────────────────────────────────────
    t0 = _step(2, total, "Diarising (whisperx / pyannote)")
    turns = await diarization.diarize(audio_path)
    _done(t0)
    speakers_found = sorted({t["speaker"] for t in turns})
    print(f"  speakers={len(speakers_found)}  turns={len(turns)}  "
          f"labels={', '.join(speakers_found)}")

    # ── 3. Merge ───────────────────────────────────────────────────────────────
    t0 = _step(3, total, "Merging transcript with speaker turns")
    merged = diarization.merge_transcript_with_diarization(segments, turns)
    _done(t0)
    print(f"  merged segments={len(merged)}")
    for seg in merged[:5]:
        print(f"  {_fmt_time(seg['start'])}  {seg['speaker']:12}  {seg['text'][:80]}")
    if len(merged) > 5:
        print(f"  ... ({len(merged) - 5} more)")

    # ── 4. Assign roles ────────────────────────────────────────────────────────
    print(f"\n[4/{total}] Assigning speaker roles (first speaker = interpreter)")
    unique_speakers = list(dict.fromkeys(s["speaker"] for s in merged
                                         if s["speaker"] != "UNKNOWN"))
    if len(unique_speakers) < 2:
        print(f"  WARNING: fewer than 2 speakers found — {unique_speakers}")
        interpreter_speaker = unique_speakers[0] if unique_speakers else "SPEAKER_00"
    else:
        interpreter_speaker = unique_speakers[0]
        client_speaker = unique_speakers[1]
        print(f"  interpreter → {interpreter_speaker}")
        print(f"  client      → {client_speaker}")

    # ── 5. Split by speaker ────────────────────────────────────────────────────
    print(f"\n[5/{total}] Splitting segments by speaker role")
    interp_texts, client_texts = _split_by_speaker(merged, interpreter_speaker)
    print(f"  interpreter segments={len(interp_texts)}  client segments={len(client_texts)}")
    if not interp_texts or not client_texts:
        print("  ERROR: not enough segments to score. Exiting.")
        return

    # ── 6. Score ───────────────────────────────────────────────────────────────
    t0 = _step(6, total, "Scoring (LaBSE semantic similarity)")
    scores = await scoring.score_segments(client_texts, interp_texts)
    _done(t0)
    agg = scoring.aggregate_scores(scores)
    print(f"  mean={agg['mean']:.3f}  min={agg['min']:.3f}  max={agg['max']:.3f}  "
          f"pairs={len(scores)}")

    # ── 7. LLM feedback ────────────────────────────────────────────────────────
    t0 = _step(7, total, "Generating LLM feedback (Anthropic)")
    feedback_text = await feedback.generate_feedback({"segments": merged}, scores)
    _done(t0)

    print("\n" + "═" * 60)
    print("FEEDBACK")
    print("═" * 60)
    print(feedback_text)
    print("═" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Tolkcheck AI stack smoke test")
    parser.add_argument("audio", type=Path, help="Path to the audio file")
    parser.add_argument("--language", default="nl",
                        help="Source language code (default: nl)")
    args = parser.parse_args()

    if not args.audio.exists():
        print(f"ERROR: file not found: {args.audio}")
        raise SystemExit(1)

    asyncio.run(main(args.audio, args.language))
