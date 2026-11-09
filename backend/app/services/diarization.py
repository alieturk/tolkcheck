"""Speaker diarization via pyannote.audio Pipeline.

Uses pyannote/speaker-diarization-3.1 directly.

NOTE ON WHISPERX: this pipeline does not use WhisperX at any stage. Earlier
revisions depended on it, and this module's docstring implied its diarization
wrapper was in play — it was not (whisperx no longer exposes
DiarizationPipeline publicly), and neither was its forced phoneme alignment
(`whisperx.align`) or its VAD Cut & Merge. WhisperX has been dropped as a
dependency in favour of pyannote.audio directly.

To be fair to the alternative: language coverage was NOT the obstacle. WhisperX's
`DEFAULT_ALIGN_MODELS_HF` map carries wav2vec2 alignment models for 35 languages
including both `tr` and `nl`, so forced alignment for this language pair was
available. (Only the smaller `DEFAULT_ALIGN_MODELS_TORCH` map is limited, to
de/en/es/fr/it.) The reason it is not wired in is simpler:

  Nothing downstream consumes word-level timestamps. alignment.py merges segments
  into speaker blocks with a 3 s gap threshold, and scoring.py compares block
  *text*. Sub-second timestamp precision changes no score anywhere in the
  pipeline, so alignment would add a second wav2vec2 model per language on CPU
  for no measurable effect on any output.

Revisit this if word-level timing acquires a consumer — the obvious one being a
UI that jumps a reviewer to the exact moment of a flagged deviation, which would
make precise word boundaries worth their cost.

Requires:
  - HF_TOKEN set in .env (accept the model license at
    https://hf.co/pyannote/speaker-diarization-3.1)
  - pip: pyannote.audio (brings in torch)
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from app.config import settings

log = logging.getLogger(__name__)

# Silence put in front of the audio before diarization. A recording that starts with
# speech at t=0 gave pyannote too little context: the first sentence was cut after
# about a second and its tail assigned to another speaker. Times are shifted back.
LEAD_IN_SILENCE_S = 2.0


def _remove_lead_in(turns: list[dict], lead_in_s: float = LEAD_IN_SILENCE_S) -> list[dict]:
    """Shift turns back to the original timeline; anything inside the lead-in goes."""
    shifted = []
    for turn in turns:
        start = max(0.0, turn["start"] - lead_in_s)
        end = max(0.0, turn["end"] - lead_in_s)
        if end > start:
            shifted.append({**turn, "start": start, "end": end})
    return shifted


async def diarize(audio_path: Path, num_speakers: int | None = None) -> list[dict]:
    """Async wrapper — offloads CPU/GPU-bound work to the default thread pool."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _diarize_sync, audio_path, num_speakers)


def _diarize_sync(audio_path: Path, num_speakers: int | None) -> list[dict]:
    from pyannote.audio import Pipeline
    import torchaudio

    pipeline = Pipeline.from_pretrained(
        "pyannote/speaker-diarization-3.1",
        token=settings.hf_token, # Soms is 'use_auth_token' nodig ipv 'token'
    )

    # Zorg dat de pipeline op de CPU draait (of GPU indien beschikbaar)
    # Voor een MacBook Air (Docker) is CPU het veiligst
    import torch
    pipeline.to(torch.device("cpu"))

    kwargs: dict = {}
    if num_speakers is not None:
        kwargs["num_speakers"] = num_speakers

    # Audio laden via torchaudio (zoals je al deed, dit is goed voor MP3 nu)
    waveform, sample_rate = torchaudio.load(str(audio_path))
    lead_in = torch.zeros(waveform.shape[0], int(LEAD_IN_SILENCE_S * sample_rate))
    audio_input = {"waveform": torch.cat([lead_in, waveform], dim=1), "sample_rate": sample_rate}

    # Uitvoeren van de pipeline
    result = pipeline(audio_input, **kwargs)
    # In pyannote >= 3.3 the pipeline returns DiarizeOutput; the Annotation
    # lives under .speaker_diarization.  Older versions returned the Annotation
    # directly — handle both.
    annotation = getattr(result, "speaker_diarization", result)

    turns = []
    for segment, track, speaker in annotation.itertracks(yield_label=True):
        turns.append({
            "start": float(segment.start),
            "end": float(segment.end),
            "speaker": str(speaker)
        })
    turns = _remove_lead_in(turns)

    # Summarise diarization output so misassignments are immediately visible
    from collections import Counter
    counts = Counter(t["speaker"] for t in turns)
    log.info("diarize  file=%s  total_turns=%d  speakers=%s",
             audio_path.name, len(turns),
             {spk: cnt for spk, cnt in sorted(counts.items())})
    for turn in turns:
        log.debug("diarize  turn  speaker=%-12s  %.2f–%.2fs",
                  turn["speaker"], turn["start"], turn["end"])

    # Warn about overlapping turns (indicates diarization confusion)
    sorted_turns = sorted(turns, key=lambda t: t["start"])
    for i in range(1, len(sorted_turns)):
        prev, curr = sorted_turns[i - 1], sorted_turns[i]
        overlap = prev["end"] - curr["start"]
        if overlap > 0.1:
            log.warning(
                "diarize  OVERLAP  %s %.2f–%.2fs  overlaps  %s %.2f–%.2fs  by %.2fs",
                prev["speaker"], prev["start"], prev["end"],
                curr["speaker"], curr["start"], curr["end"],
                overlap,
            )

    return turns