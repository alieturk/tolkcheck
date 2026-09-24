"""ASR confidence scoring — replaces binary reliability flag with continuous score (0-1).

Whisper's per-segment quality signals (avg_logprob, compression_ratio, no_speech_prob)
are weighted to produce a confidence score for each segment. Confidence is language-specific:
Turkish (morphologically rich, lower-resource language) gets different thresholds than Dutch.

The confidence score is 0 (very unreliable) to 1 (very reliable), allowing:
- Continuous filtering (not binary exclude/include)
- Language-specific tuning
- Better feedback generation (high/medium/low severity instead of skip/include)
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)

# Thresholds per language (based on Whisper's published gates but tuned)
THRESHOLDS = {
    "nl": {
        "logprob_floor": -0.8,      # Dutch has more training data, higher baseline
        "compression_ceiling": 2.0,  # Less tolerance for repetition
        "no_speech_ceiling": 0.4,    # Less false speech detection
    },
    "tr": {
        "logprob_floor": -1.2,       # Turkish is lower-resource, needs margin
        "compression_ceiling": 2.5,  # More tolerant of morphological repetition
        "no_speech_ceiling": 0.5,    # More tolerant of silence
    },
    "default": {
        "logprob_floor": -1.0,
        "compression_ceiling": 2.4,
        "no_speech_ceiling": 0.6,
    },
}

# Feature weights per language (how much each factor matters)
WEIGHTS = {
    "nl": {
        "logprob": 0.4,
        "compression": 0.3,
        "no_speech": 0.3,
    },
    "tr": {
        "logprob": 0.4,
        "compression": 0.35,
        "no_speech": 0.25,
    },
    "default": {
        "logprob": 0.33,
        "compression": 0.33,
        "no_speech": 0.34,
    },
}


def compute_confidence_score(
    avg_logprob: float | None,
    compression_ratio: float | None,
    no_speech_prob: float | None,
    language: str = "nl",
) -> float:
    """Compute ASR confidence score (0-1) for a single segment.

    Args:
        avg_logprob: Whisper's average log probability (typically -0.5 to -2.0)
        compression_ratio: Character count / audio duration (typically 1.0-2.5)
        no_speech_prob: Probability segment is silence (0.0-1.0)
        language: Language code ("nl", "tr", or other → uses default)

    Returns:
        Confidence score 0-1 where:
        - 1.0 = very reliable
        - 0.7-0.9 = reliable with minor issues
        - 0.5-0.7 = questionable
        - <0.5 = very unreliable
    """
    thresholds = THRESHOLDS.get(language, THRESHOLDS["default"])
    weights = WEIGHTS.get(language, WEIGHTS["default"])

    # Component 1: Logprob quality (higher is better, floor is worst)
    logprob_score = 0.5
    if avg_logprob is not None:
        logprob_score = max(0.0, min(1.0,
            (avg_logprob - thresholds["logprob_floor"]) / (-thresholds["logprob_floor"])
        ))

    # Component 2: Compression quality (lower is better, ceiling is worst)
    compression_score = 0.5
    if compression_ratio is not None:
        compression_score = max(0.0, min(1.0,
            1.0 - (compression_ratio / thresholds["compression_ceiling"])
        ))

    # Component 3: Speech detection quality (lower no_speech_prob is better)
    speech_score = 0.5
    if no_speech_prob is not None:
        speech_score = max(0.0, min(1.0,
            1.0 - (no_speech_prob / thresholds["no_speech_ceiling"])
        ))

    # Weighted combination
    confidence = (
        logprob_score * weights["logprob"]
        + compression_score * weights["compression"]
        + speech_score * weights["no_speech"]
    )

    return round(confidence, 3)


def compute_block_confidence(segments: list[dict], language: str = "nl") -> float:
    """Compute confidence for an entire block (worst-case of its segments).

    A block is only as good as its worst segment — one hallucinated segment
    ruins the whole block's trustworthiness.
    """
    if not segments:
        return 1.0  # Empty block is neutral

    segment_scores = []
    for seg in segments:
        score = compute_confidence_score(
            seg.get("avg_logprob"),
            seg.get("compression_ratio"),
            seg.get("no_speech_prob"),
            language=language,
        )
        segment_scores.append(score)

    # Return minimum score (worst-case)
    return min(segment_scores) if segment_scores else 1.0


def confidence_to_severity(confidence: float) -> str:
    """Map confidence score to issue severity level.

    Used in feedback generation to categorize how much to trust a pair.
    """
    if confidence >= 0.8:
        return "none"  # No ASR issue
    elif confidence >= 0.65:
        return "low"  # Slight ASR degradation
    elif confidence >= 0.5:
        return "medium"  # Noticeable ASR issues
    else:
        return "high"  # Very unreliable ASR


def confidence_to_label(confidence: float) -> str:
    """Human-readable label for confidence score."""
    severity = confidence_to_severity(confidence)
    return f"{confidence:.1%} ({severity})"
