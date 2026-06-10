"""Shared pytest fixtures and helpers."""
from __future__ import annotations


def make_seg(
    speaker: str,
    text: str,
    start: float = 0.0,
    end: float = 1.0,
    language: str = "nl",
) -> dict:
    """Build a transcript segment dict — the canonical shape used throughout the pipeline."""
    return {"speaker": speaker, "text": text, "start": start, "end": end, "language": language}
