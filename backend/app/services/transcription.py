"""Whisper transcription via faster-whisper (lazy-loaded, thread-pool).

Model is whatever ``settings.whisper_model`` names (default ``large-v3`` — see
config.py for why that default rather than ``turbo``). faster-whisper is used
directly; WhisperX is not involved in this module, so no forced phoneme
alignment happens here and segment timestamps are Whisper's own.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from app.config import settings

log = logging.getLogger(__name__)

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


async def transcribe(
    audio_path: Path,
    language: str | None = None,
    initial_prompt: str | None = None,
) -> dict:
    """Async wrapper — offloads CPU-bound work to the default thread pool."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, _transcribe_sync, audio_path, language, initial_prompt
    )


def _transcribe_sync(
    audio_path: Path,
    language: str | None,
    initial_prompt: str | None = None,
) -> dict:
    model = _get_model()
    kwargs: dict = {"beam_size": 5, "vad_filter": True}
    if language:
        kwargs["language"] = language
    if initial_prompt:
        kwargs["initial_prompt"] = initial_prompt
    segments, info = model.transcribe(str(audio_path), **kwargs)
    detected = info.language
    seg_list = [
        {
            "start": seg.start,
            "end": seg.end,
            "text": seg.text.strip(),
            "language": language or detected,
        }
        for seg in segments
    ]
    log.info("transcribe  file=%s  forced_lang=%s  detected=%s  prob=%.2f  segments=%d",
             audio_path.name, language or "auto", detected,
             info.language_probability, len(seg_list))
    return {
        "language": detected,
        "language_probability": info.language_probability,
        "duration": info.duration,
        "segments": seg_list,
    }


async def transcribe_chunk(
    waveform: "torch.Tensor",
    sample_rate: int,
    language: str | None = None,
    initial_prompt: str | None = None,
) -> list[dict]:
    """Transcribe a pre-loaded waveform slice (e.g. one speaker turn).

    initial_prompt, when given, biases Whisper's decode toward the text it
    contains — used to pass a per-session glossary (client name, place names,
    case-specific terms; see Session.known_terms) so proper nouns are less
    likely to be mis-transcribed into something that looks like a translation
    error downstream. Because transcription here is per diarization turn (not
    one call over the whole file), the prompt is freshly re-applied on every
    turn rather than decaying over a long recording the way a single
    whole-file initial_prompt would.

    Returns a list of segment dicts with start/end/text/language.
    Timestamps are relative to the start of the chunk — callers must
    add the turn's absolute offset before storing.
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, _transcribe_chunk_sync, waveform, sample_rate, language, initial_prompt
    )


def _transcribe_chunk_sync(
    waveform: "torch.Tensor",
    sample_rate: int,
    language: str | None,
    initial_prompt: str | None = None,
) -> list[dict]:
    import numpy as np
    import torchaudio.functional as F

    model = _get_model()

    # Mono, float32, 16 kHz — Whisper's expected input format
    audio = waveform.mean(dim=0) if waveform.dim() == 2 else waveform
    if sample_rate != 16000:
        audio = F.resample(audio, sample_rate, 16000)
    audio_np: np.ndarray = audio.numpy().astype(np.float32)

    # vad_filter=False: the compact waveform is already speaker-isolated speech,
    # so Silero VAD would only discard real speech at artificial gap boundaries.
    kwargs: dict = {"beam_size": 5, "vad_filter": False}
    if language:
        kwargs["language"] = language
    if initial_prompt:
        kwargs["initial_prompt"] = initial_prompt

    segments, info = model.transcribe(audio_np, **kwargs)
    detected = info.language
    result = [
        {
            "start": seg.start,
            "end": seg.end,
            "text": seg.text.strip(),
            "language": language or detected,
        }
        for seg in segments
        if seg.text.strip()
    ]
    log.info("transcribe_chunk  forced_lang=%s  detected=%s  prob=%.2f  segments=%d",
             language or "auto", detected, info.language_probability, len(result))
    for seg in result:
        log.debug("transcribe_chunk  %.2f–%.2fs  %r",
                  seg["start"], seg["end"], seg["text"][:80].replace("\n", " "))
    return result
