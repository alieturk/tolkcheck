"""Speaker diarization via pyannote.audio Pipeline.

Uses pyannote/speaker-diarization-3.1 directly (whisperx pulls it in as a
dependency but no longer exposes DiarizationPipeline at its public API).

Requires:
  - HF_TOKEN set in .env (accept the model license at
    https://hf.co/pyannote/speaker-diarization-3.1)
  - pip: whisperx (brings in pyannote.audio + torch)
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from app.config import settings


async def diarize(audio_path: Path, num_speakers: int | None = None) -> list[dict]:
    """Async wrapper — offloads CPU/GPU-bound work to the default thread pool."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _diarize_sync, audio_path, num_speakers)


def _diarize_sync(audio_path: Path, num_speakers: int | None) -> list[dict]:
    from pyannote.audio import Pipeline

    pipeline = Pipeline.from_pretrained(
        "pyannote/speaker-diarization-3.1",
        use_auth_token=settings.hf_token,
    )

    kwargs: dict = {}
    if num_speakers is not None:
        kwargs["num_speakers"] = num_speakers

    annotation = pipeline(str(audio_path), **kwargs)

    return [
        {"start": turn.start, "end": turn.end, "speaker": speaker}
        for turn, _, speaker in annotation.itertracks(yield_label=True)
    ]


def merge_transcript_with_diarization(
    transcript_segments: list[dict],
    diarization_segments: list[dict],
) -> list[dict]:
    """Assign a speaker label to each Whisper segment by overlap with diarization."""
    merged = []
    for seg in transcript_segments:
        speaker = _find_dominant_speaker(seg["start"], seg["end"], diarization_segments)
        merged.append({**seg, "speaker": speaker})
    return merged


def _find_dominant_speaker(
    start: float, end: float, diarization: list[dict]
) -> str:
    overlap: dict[str, float] = {}
    for d in diarization:
        o = min(end, d["end"]) - max(start, d["start"])
        if o > 0:
            overlap[d["speaker"]] = overlap.get(d["speaker"], 0.0) + o
    return max(overlap, key=overlap.get) if overlap else "UNKNOWN"  # type: ignore[arg-type]
