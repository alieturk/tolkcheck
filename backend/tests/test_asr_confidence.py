"""Tests for services/asr_confidence.py — continuous confidence scoring.

Replaces binary unreliable flag with continuous 0-1 confidence scores that are
language-specific and weighted by logprob, compression ratio, and no_speech_prob.
"""
from __future__ import annotations

import pytest

from app.services import asr_confidence
from tests.conftest import make_seg


class TestComputeConfidenceScore:
    """Test single-segment confidence scoring."""

    def test_perfect_segment(self):
        """High confidence for clean segment."""
        score = asr_confidence.compute_confidence_score(
            avg_logprob=-0.3,
            compression_ratio=1.1,
            no_speech_prob=0.1,
            language="nl",
        )
        assert score > 0.6  # Very good but not perfect (no_speech still contributes)

    def test_poor_segment(self):
        """Low confidence for hallucinated segment."""
        score = asr_confidence.compute_confidence_score(
            avg_logprob=-2.0,
            compression_ratio=3.0,
            no_speech_prob=0.8,
            language="nl",
        )
        assert score < 0.4

    def test_language_specific_tuning_nl(self):
        """Dutch has tighter thresholds."""
        score_nl = asr_confidence.compute_confidence_score(
            avg_logprob=-1.1,
            compression_ratio=2.3,
            no_speech_prob=0.55,
            language="nl",
        )
        assert score_nl < 0.5  # Dutch doesn't tolerate this

    def test_language_specific_tuning_tr(self):
        """Turkish has looser thresholds (lower-resource language)."""
        score_tr = asr_confidence.compute_confidence_score(
            avg_logprob=-0.8,  # Good logprob
            compression_ratio=2.1,  # Within Turkish ceiling (2.5)
            no_speech_prob=0.3,    # Below Turkish ceiling (0.5)
            language="tr",
        )
        # Score should be reasonable (not perfect but not terrible)
        assert score_tr > 0.25

    def test_missing_signals_default_to_neutral(self):
        """Missing signals don't crash, default to 0.5."""
        score = asr_confidence.compute_confidence_score(
            avg_logprob=None,
            compression_ratio=None,
            no_speech_prob=None,
            language="nl",
        )
        # All components at 0.5, result should be 0.5
        assert 0.45 < score < 0.55

    def test_single_bad_signal_tanks_confidence(self):
        """One very bad signal dominates the score."""
        score = asr_confidence.compute_confidence_score(
            avg_logprob=-2.5,  # Very bad
            compression_ratio=1.2,  # Good
            no_speech_prob=0.15,  # Good
            language="nl",
        )
        assert score < 0.5  # Dominated by bad logprob

    def test_default_language(self):
        """Unknown language falls back to defaults."""
        score = asr_confidence.compute_confidence_score(
            avg_logprob=-0.5,
            compression_ratio=1.5,
            no_speech_prob=0.2,
            language="ja",  # Unknown
        )
        assert 0.4 < score < 0.7  # Reasonable score with defaults


class TestBlockConfidence:
    """Test block-level confidence (worst-case of segments)."""

    def test_block_is_as_good_as_worst_segment(self):
        """Block confidence is minimum of segment confidences."""
        segments = [
            make_seg("sp1", "text1", 0, 2, avg_logprob=-0.3, compression_ratio=1.1, no_speech_prob=0.1),
            make_seg("sp1", "text2", 2, 4, avg_logprob=-2.0, compression_ratio=3.0, no_speech_prob=0.8),
        ]
        block_conf = asr_confidence.compute_block_confidence(segments, language="nl")
        # Should be influenced heavily by the poor segment
        assert block_conf < 0.5

    def test_empty_block_is_neutral(self):
        """Empty block has no confidence issue."""
        block_conf = asr_confidence.compute_block_confidence([], language="nl")
        assert block_conf == 1.0

    def test_single_segment_block(self):
        """Single-segment block returns that segment's confidence."""
        segments = [
            make_seg("sp1", "text", 0, 2, avg_logprob=-0.5, compression_ratio=1.2, no_speech_prob=0.2),
        ]
        block_conf = asr_confidence.compute_block_confidence(segments, language="nl")
        single_conf = asr_confidence.compute_confidence_score(
            avg_logprob=-0.5,
            compression_ratio=1.2,
            no_speech_prob=0.2,
            language="nl",
        )
        assert block_conf == single_conf


class TestConfidenceToSeverity:
    """Test severity level mapping."""

    def test_very_reliable(self):
        """High confidence → no severity."""
        assert asr_confidence.confidence_to_severity(0.95) == "none"

    def test_reliable_with_minor_issues(self):
        """0.65-0.79 → low severity."""
        assert asr_confidence.confidence_to_severity(0.70) == "low"

    def test_questionable(self):
        """0.5-0.64 → medium severity."""
        assert asr_confidence.confidence_to_severity(0.55) == "medium"

    def test_very_unreliable(self):
        """<0.5 → high severity."""
        assert asr_confidence.confidence_to_severity(0.45) == "high"

    def test_boundary_cases(self):
        """Test boundaries explicitly."""
        assert asr_confidence.confidence_to_severity(0.80) == "none"
        assert asr_confidence.confidence_to_severity(0.79) == "low"
        assert asr_confidence.confidence_to_severity(0.65) == "low"
        assert asr_confidence.confidence_to_severity(0.64) == "medium"
        assert asr_confidence.confidence_to_severity(0.50) == "medium"
        assert asr_confidence.confidence_to_severity(0.49) == "high"


class TestConfidenceToLabel:
    """Test human-readable labels."""

    def test_label_format(self):
        """Label includes percentage and severity."""
        label = asr_confidence.confidence_to_label(0.75)
        assert "75" in label  # Percentage included
        assert "%" in label
        assert "low" in label

    def test_label_ranges(self):
        """Labels correctly reflect severity ranges."""
        assert "none" in asr_confidence.confidence_to_label(0.9)
        assert "high" in asr_confidence.confidence_to_label(0.4)


class TestLanguageSpecificWeighting:
    """Test that language affects scoring appropriately."""

    def test_turkish_vs_dutch_morphology(self):
        """Turkish allows higher compression (morphological agglutination)."""
        # Segmentrepeated due to morphology (not hallucination)
        score_tr = asr_confidence.compute_confidence_score(
            avg_logprob=-0.8,
            compression_ratio=2.3,  # High but normal for morphology
            no_speech_prob=0.25,
            language="tr",
        )

        # Same segment scored as Dutch
        score_nl = asr_confidence.compute_confidence_score(
            avg_logprob=-0.8,
            compression_ratio=2.3,
            no_speech_prob=0.25,
            language="nl",
        )

        # Turkish should be more confident about this
        assert score_tr > score_nl
