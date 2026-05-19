"""Whisper large-v3 transcription via faster-whisper (lazy-loaded, thread-pool)."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

from app.config import settings

if TYPE_CHECKING:
    from faster_whisper import WhisperModel
    import torch

_model: WhisperModel | None = None


def _get_model() -> WhisperModel:
    global _model
    if _model is None:
        from faster_whisper import WhisperModel

        _model = WhisperModel(
            settings.whisper_model,
            device=settings.whisper_device,
            compute_type=settings.whisper_compute_type,
        )
    return _model


async def transcribe(audio_path: Path, language: str | None = None) -> dict:
    """Async wrapper — offloads CPU-bound work to the default thread pool."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _transcribe_sync, audio_path, language)


def _transcribe_sync(audio_path: Path, language: str | None) -> dict:
    model = _get_model()
    kwargs: dict = {"beam_size": 5, "vad_filter": True}
    if language:
        kwargs["language"] = language
    segments, info = model.transcribe(str(audio_path), **kwargs)
    detected = info.language
    return {
        "language": detected,
        "language_probability": info.language_probability,
        "duration": info.duration,
        "segments": [
            {
                "start": seg.start,
                "end": seg.end,
                "text": seg.text.strip(),
                "language": language or detected,
            }
            for seg in segments
        ],
    }


async def transcribe_chunk(
    waveform: "torch.Tensor",
    sample_rate: int,
    language: str | None = None,
) -> list[dict]:
    """Transcribe a pre-loaded waveform slice (e.g. one speaker turn).

    Returns a list of segment dicts with start/end/text/language.
    Timestamps are relative to the start of the chunk — callers must
    add the turn's absolute offset before storing.
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, _transcribe_chunk_sync, waveform, sample_rate, language
    )


def _transcribe_chunk_sync(
    waveform: "torch.Tensor",
    sample_rate: int,
    language: str | None,
) -> list[dict]:
    import numpy as np
    import torchaudio.functional as F

    model = _get_model()

    # Mono, float32, 16 kHz — Whisper's expected input format
    audio = waveform.mean(dim=0) if waveform.dim() == 2 else waveform
    if sample_rate != 16000:
        audio = F.resample(audio, sample_rate, 16000)
    audio_np: np.ndarray = audio.numpy().astype(np.float32)

    kwargs: dict = {"beam_size": 5, "vad_filter": True}
    if language:
        kwargs["language"] = language

    segments, info = model.transcribe(audio_np, **kwargs)
    detected = info.language
    return [
        {
            "start": seg.start,
            "end": seg.end,
            "text": seg.text.strip(),
            "language": language or detected,
        }
        for seg in segments
        if seg.text.strip()
    ]
