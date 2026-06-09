"""Unit tests for the pure helper functions in services/diarization.py.

_find_dominant_speaker and merge_transcript_with_diarization do not load
any models — they are pure overlap-calculation functions.
"""
from __future__ import annotations

import pytest

from app.services.diarization import _find_dominant_speaker, merge_transcript_with_diarization


def diar(speaker: str, start: float, end: float) -> dict:
    return {"speaker": speaker, "start": start, "end": end}


def seg(text: str, start: float, end: float) -> dict:
    return {"text": text, "start": start, "end": end, "language": "nl"}


# ── _find_dominant_speaker ────────────────────────────────────────────────────

class TestFindDominantSpeaker:
    def test_perfect_overlap(self):
        """Segment fully inside one speaker's turn → that speaker wins."""
        d = [diar("SPK_A", 0, 10)]
        assert _find_dominant_speaker(2, 8, d) == "SPK_A"

    def test_no_overlap_returns_unknown(self):
        """Segment with no diarization overlap → UNKNOWN."""
        d = [diar("SPK_A", 0, 5)]
        assert _find_dominant_speaker(10, 15, d) == "UNKNOWN"

    def test_empty_diarization_returns_unknown(self):
        assert _find_dominant_speaker(0, 5, []) == "UNKNOWN"

    def test_two_speakers_majority_wins(self):
        """Segment overlaps both speakers — the one with more overlap wins."""
        d = [
            diar("SPK_A", 0, 3),   # overlaps 0–3 → 3s
            diar("SPK_B", 3, 10),  # overlaps 3–8 → 5s
        ]
        assert _find_dominant_speaker(0, 8, d) == "SPK_B"

    def test_exact_tie_is_deterministic(self):
        """With equal overlap, max() picks whichever comes first alphabetically."""
        d = [
            diar("SPK_A", 0, 5),
            diar("SPK_B", 5, 10),
        ]
        result = _find_dominant_speaker(0, 10, d)
        assert result in ("SPK_A", "SPK_B")  # deterministic, not a crash

    def test_partial_overlap_at_boundary(self):
        """Only a sliver of overlap — still counts."""
        d = [diar("SPK_A", 4, 10)]
        assert _find_dominant_speaker(0, 5, d) == "SPK_A"

    def test_zero_length_overlap_excluded(self):
        """Adjacent segments (end == start) produce zero overlap — not counted."""
        d = [diar("SPK_A", 5, 10)]
        # Segment ends exactly where diarization starts → min(5,10)–max(5,5) = 0
        assert _find_dominant_speaker(0, 5, d) == "UNKNOWN"

    def test_three_speakers_correct_winner(self):
        d = [
            diar("SPK_A", 0, 2),   # 2s
            diar("SPK_B", 2, 5),   # 3s
            diar("SPK_C", 5, 20),  # 5s of overlap (5–10)
        ]
        assert _find_dominant_speaker(0, 10, d) == "SPK_C"

    def test_diarization_turn_entirely_outside_segment(self):
        d = [diar("SPK_A", 100, 200)]
        assert _find_dominant_speaker(0, 10, d) == "UNKNOWN"

    def test_multiple_turns_same_speaker_accumulated(self):
        """Multiple diarization turns for the same speaker are summed."""
        d = [
            diar("SPK_A", 0, 3),    # 3s
            diar("SPK_B", 3, 5),    # 2s
            diar("SPK_A", 5, 8),    # 3s → SPK_A total = 6s
        ]
        assert _find_dominant_speaker(0, 8, d) == "SPK_A"


# ── merge_transcript_with_diarization ─────────────────────────────────────────

class TestMergeTranscriptWithDiarization:
    def test_perfect_alignment(self):
        """Each Whisper segment maps cleanly to the correct speaker."""
        transcript = [
            seg("Goede morgen.", 0, 5),
            seg("Ik ben leraar.", 10, 18),
        ]
        diarization = [
            diar("OFFICER", 0, 6),
            diar("CLIENT",  9, 20),
        ]
        result = merge_transcript_with_diarization(transcript, diarization)
        assert result[0]["speaker"] == "OFFICER"
        assert result[1]["speaker"] == "CLIENT"

    def test_original_fields_preserved(self):
        """Merge does not remove any existing segment fields."""
        transcript = [seg("Tekst.", 0, 5)]
        diarization = [diar("SPK_A", 0, 6)]
        result = merge_transcript_with_diarization(transcript, diarization)
        assert result[0]["text"] == "Tekst."
        assert result[0]["start"] == 0
        assert result[0]["end"] == 5
        assert result[0]["language"] == "nl"

    def test_no_overlap_assigns_unknown(self):
        transcript = [seg("Tekst.", 100, 105)]
        diarization = [diar("SPK_A", 0, 10)]
        result = merge_transcript_with_diarization(transcript, diarization)
        assert result[0]["speaker"] == "UNKNOWN"

    def test_empty_transcript(self):
        diarization = [diar("SPK_A", 0, 10)]
        assert merge_transcript_with_diarization([], diarization) == []

    def test_empty_diarization(self):
        transcript = [seg("Tekst.", 0, 5)]
        result = merge_transcript_with_diarization(transcript, [])
        assert result[0]["speaker"] == "UNKNOWN"

    def test_overlapping_speakers_dominant_wins(self):
        """Segment overlapping two speakers is assigned to the one with more overlap."""
        transcript = [seg("Overlap.", 2, 10)]
        diarization = [
            diar("SPK_A", 0, 4),   # overlap 2–4 = 2s
            diar("SPK_B", 4, 12),  # overlap 4–10 = 6s → wins
        ]
        result = merge_transcript_with_diarization(transcript, diarization)
        assert result[0]["speaker"] == "SPK_B"

    def test_multiple_segments_correct_order(self):
        """Result preserves original segment order."""
        transcript = [seg(f"Seg{i}.", i * 10, i * 10 + 5) for i in range(4)]
        diarization = [diar(f"SPK_{i}", i * 10, i * 10 + 8) for i in range(4)]
        result = merge_transcript_with_diarization(transcript, diarization)
        for i, r in enumerate(result):
            assert r["text"] == f"Seg{i}."
            assert r["speaker"] == f"SPK_{i}"

    def test_realistic_ind_scenario(self):
        """Three-speaker IND session: officer, client (Dari), interpreter (Dutch)."""
        transcript = [
            seg("Goedemorgen.", 0, 3),
            seg("نام من احمد است.", 5, 12),
            seg("Mijn naam is Ahmad.", 14, 19),
        ]
        diarization = [
            diar("OFFICER",  0,  4),
            diar("CLIENT",   4, 13),
            diar("INTERP",  13, 20),
        ]
        result = merge_transcript_with_diarization(transcript, diarization)
        assert result[0]["speaker"] == "OFFICER"
        assert result[1]["speaker"] == "CLIENT"
        assert result[2]["speaker"] == "INTERP"
