"""Standalone AI stack smoke test — no database required.

Usage (inside the worker container):
    uv run python smoke_test.py /app/uploads/<filename> [--language tr] [--interpreter-speaker SPEAKER_02 --client-speaker SPEAKER_01]

Steps:
    0. File info (name, size, sha256 fingerprint, audio properties)
    1. Transcribe (Whisper large-v3)
    2. Diarise (whisperx / pyannote)
    3. Merge transcript with speaker turns
    4. Assign interpreter / client roles
    5. Split segments by role
    6. Score (LaBSE cosine similarity)
    7. Generate LLM feedback (Anthropic)
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import time
from pathlib import Path


def _fmt_time(seconds: float) -> str:
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m}:{s:02d}"


def _human_size(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def _sha256_prefix(path: Path, chars: int = 16) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()[:chars]


def _step(n: int, total: int, label: str) -> float:
    print(f"\n[{n}/{total}] {label}...", flush=True)
    return time.perf_counter()


def _done(t0: float) -> None:
    print(f"  done in {time.perf_counter() - t0:.1f}s", flush=True)


def _print_file_info(audio_path: Path) -> None:
    import torchaudio

    stat = audio_path.stat()
    sha = _sha256_prefix(audio_path)

    print("\n" + "═" * 60)
    print("FILE")
    print("═" * 60)
    print(f"  name        : {audio_path.name}")
    print(f"  size        : {_human_size(stat.st_size)}")
    print(f"  sha256      : {sha}...")
    print(f"  format      : {audio_path.suffix.lstrip('.')}")

    try:
        info = torchaudio.info(str(audio_path))
        duration_s = info.num_frames / info.sample_rate
        print(f"  duration    : {_fmt_time(duration_s)}  ({duration_s:.1f}s)")
        print(f"  sample_rate : {info.sample_rate} Hz")
        print(f"  channels    : {info.num_channels}  "
              f"({'mono' if info.num_channels == 1 else 'stereo' if info.num_channels == 2 else 'multi'})")
    except Exception as e:
        print(f"  [torchaudio.info failed: {e}]")

    print("═" * 60, flush=True)


async def main(
    audio_path: Path,
    language: str | None,
    interpreter_speaker_arg: str | None,
    client_speaker_arg: str | None,
) -> None:
    from app.services import alignment, diarization, feedback, scoring, transcription
    from app.pipeline import _filter_hallucinations

    total = 7

    # ── File info (step 0) ─────────────────────────────────────────────────────
    _print_file_info(audio_path)

    # ── 1. Diarise ────────────────────────────────────────────────────────────
    t0 = _step(1, total, "Diarising (pyannote) — language-agnostic first pass")
    turns = await diarization.diarize(audio_path, num_speakers=3)
    _done(t0)
    speakers_found = sorted({t["speaker"] for t in turns})
    print(f"  speakers={len(speakers_found)}  turns={len(turns)}  "
          f"labels={', '.join(speakers_found)}")

    # ── 2. Transcribe each diarization turn individually ──────────────────────
    # Per-turn (not per-speaker) so each short utterance gets its own language
    # detection. The interpreter speaks both Dutch and the client's language;
    # compacting per-speaker locks Whisper to Dutch and garbles the relay turns.
    t0 = _step(2, total, "Transcribing per turn (Whisper — language auto-detected per turn)")
    import torchaudio
    waveform, sr = torchaudio.load(str(audio_path))
    all_segments: list[dict] = []
    lang_counts: dict[str, int] = {}

    for turn in sorted(turns, key=lambda t: t["start"]):
        s = int(turn["start"] * sr)
        e = int(turn["end"] * sr)
        chunk = waveform[:, s:e]
        if chunk.shape[-1] < 800:  # skip slivers < ~50 ms
            continue

        segs = await transcription.transcribe_chunk(chunk, sr, language)

        for seg in segs:
            seg["start"] += turn["start"]
            seg["end"]   += turn["start"]
            seg["speaker"] = turn["speaker"]
            lang_counts[seg.get("language", "?")] = (
                lang_counts.get(seg.get("language", "?"), 0) + 1
            )

        all_segments.extend(segs)
        if segs:
            print(f"  {turn['speaker']}  {_fmt_time(turn['start'])}–{_fmt_time(turn['end'])}"
                  f"  lang={segs[0].get('language', '?')}  segs={len(segs)}", flush=True)
    _done(t0)
    lang_summary = "  ".join(f"{lang}={n}" for lang, n in sorted(lang_counts.items()))
    print(f"  total segments={len(all_segments)}  languages: {lang_summary}")

    # ── 3. Sort, filter hallucinations, print ────────────────────────────────
    t0 = _step(3, total, "Filtering hallucinations and merging")
    all_segments.sort(key=lambda s: s["start"])
    merged = _filter_hallucinations(all_segments)
    _done(t0)
    removed = len(all_segments) - len(merged)
    print(f"  segments after filter={len(merged)}  hallucinations removed={removed}")
    for seg in merged:
        lang = seg.get("language", "?")
        print(f"  {_fmt_time(seg['start'])}  {seg['speaker']:12}  [{lang}]  {seg['text'][:80]}")

    # ── 4. Assign roles ────────────────────────────────────────────────────────
    print(f"\n[4/{total}] Assigning speaker roles")
    if interpreter_speaker_arg:
        interpreter_speaker = interpreter_speaker_arg
        if client_speaker_arg:
            client_speaker = client_speaker_arg
            print(f"  interpreter → {interpreter_speaker}  (manual override)")
            print(f"  client      → {client_speaker}  (manual override)")
        else:
            other = [s for s in speakers_found if s != interpreter_speaker]
            client_speaker = other[0] if other else "UNKNOWN"
            print(f"  interpreter → {interpreter_speaker}  (manual override)")
            print(f"  client      → {client_speaker}  (first non-interpreter; use --client-speaker to override)")
    else:
        unique_speakers = list(dict.fromkeys(
            s["speaker"] for s in merged if s["speaker"] != "UNKNOWN"
        ))
        if len(unique_speakers) < 2:
            print(f"  WARNING: fewer than 2 speakers found — {unique_speakers}")
            interpreter_speaker = unique_speakers[0] if unique_speakers else "SPEAKER_00"
            client_speaker = interpreter_speaker
        else:
            interpreter_speaker = unique_speakers[0]
            client_speaker = unique_speakers[1]
            print(f"  interpreter → {interpreter_speaker}  (first seen in transcript)")
            print(f"  client      → {client_speaker}")
            print(f"  tip: use --interpreter-speaker / --client-speaker to override")

    # ── 5. Build speaker blocks and classify interpreter direction ────────────
    print(f"\n[5/{total}] Building speaker blocks and classifying interpreter direction")
    blocks = alignment.build_blocks(merged, interpreter_speaker, client_speaker)
    alignment.classify_directions(blocks)
    c2o_pairs, o2c_pairs = alignment.extract_pairs(blocks)

    for b in blocks:
        direction_str = (f"  direction={b['direction']}" if b["role"] == "interpreter" else "")
        print(f"  [BLOCK] {_fmt_time(b['start'])}–{_fmt_time(b['end'])}"
              f"  {b['role']:<11}  {b['language']:<4}{direction_str}"
              f"  {b['text'][:60]!r}")
    print(f"\n  client_to_officer pairs: {len(c2o_pairs)}")
    print(f"  officer_to_client pairs: {len(o2c_pairs)}")

    if not c2o_pairs:
        print("  ERROR: no client→officer pairs found after block alignment. Exiting.")
        return

    c2o_client_texts = [p["source_block"]["text"] for p in c2o_pairs]
    c2o_interp_texts  = [p["interp_block"]["text"]  for p in c2o_pairs]
    o2c_officer_texts = [p["source_block"]["text"] for p in o2c_pairs]
    o2c_interp_texts  = [p["interp_block"]["text"]  for p in o2c_pairs]

    # ── 6. Score ───────────────────────────────────────────────────────────────
    t0 = _step(6, total, "Scoring (LaBSE semantic similarity)")
    c2o_scores = await scoring.score_segments(c2o_client_texts, c2o_interp_texts)
    o2c_scores = (
        await scoring.score_segments(o2c_officer_texts, o2c_interp_texts)
        if o2c_pairs else []
    )
    _done(t0)
    agg = scoring.aggregate_scores(c2o_scores)
    print(f"  c2o  mean={agg['mean']:.3f}  min={agg['min']:.3f}  max={agg['max']:.3f}"
          f"  pairs={len(c2o_scores)}")
    if o2c_scores:
        agg_o2c = scoring.aggregate_scores(o2c_scores)
        print(f"  o2c  mean={agg_o2c['mean']:.3f}  min={agg_o2c['min']:.3f}"
              f"  max={agg_o2c['max']:.3f}  pairs={len(o2c_scores)}")

    # Embed scoring texts (no translation in smoke test — use originals)
    for pair in c2o_pairs:
        pair["scoring_text"] = pair["source_block"]["text"]

    # ── 7. LLM feedback ────────────────────────────────────────────────────────
    t0 = _step(7, total, "Generating LLM feedback (Anthropic)")
    feedback_result = await feedback.generate_feedback(
        c2o_pairs=c2o_pairs,
        c2o_scores=c2o_scores,
        o2c_pairs=o2c_pairs,
        o2c_scores=o2c_scores,
    )
    _done(t0)

    print("\n" + "═" * 60)
    print("FEEDBACK")
    print("═" * 60)
    print(feedback_result["overall_feedback"])
    print("═" * 60)

    issues = feedback_result.get("structured_issues", [])
    if issues:
        print(f"\n{len(issues)} paar(en) geanalyseerd:")
        for pair in issues:
            pair_issues = pair.get("issues", [])
            if pair_issues:
                print(f"  Paar {pair['pair_index']}: {len(pair_issues)} probleem/problemen")
                for iss in pair_issues:
                    print(f"    [{iss['severity'].upper()}] {iss['type']}: {iss['description']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Tolkcheck AI stack smoke test")
    parser.add_argument("audio", type=Path, help="Path to the audio file")
    parser.add_argument("--language", default=None,
                        help="Source language code, e.g. nl, tr, ar (omit for auto-detect)")
    parser.add_argument("--interpreter-speaker", dest="interpreter_speaker", default=None,
                        help="Override interpreter role, e.g. --interpreter-speaker SPEAKER_02")
    parser.add_argument("--client-speaker", dest="client_speaker", default=None,
                        help="Override client role, e.g. --client-speaker SPEAKER_01")
    args = parser.parse_args()

    if not args.audio.exists():
        print(f"ERROR: file not found: {args.audio}")
        raise SystemExit(1)

    asyncio.run(main(args.audio, args.language, args.interpreter_speaker, args.client_speaker))
