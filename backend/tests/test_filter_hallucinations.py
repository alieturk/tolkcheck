"""Unit tests for _filter_hallucinations.

Whisper sometimes loops, emitting the same text segment 3+ times consecutively.
_filter_hallucinations removes any segment where the same text has already appeared
in the two immediately preceding segments.
"""
from __future__ import annotations

from app.pipeline import _filter_hallucinations
from tests.conftest import make_seg


def segs(*texts: str) -> list[dict]:
    """Build a list of segments with auto-incrementing timestamps."""
    return [make_seg("SPK", t, i * 2.0, i * 2.0 + 1.9) for i, t in enumerate(texts)]


def texts(segments: list[dict]) -> list[str]:
    return [s["text"] for s in segments]


# ── No hallucination ──────────────────────────────────────────────────────────

class TestNoHallucination:
    def test_empty(self):
        assert _filter_hallucinations([]) == []

    def test_single(self):
        result = _filter_hallucinations(segs("A"))
        assert texts(result) == ["A"]

    def test_two_identical(self):
        """Two consecutive identical segments are NOT a hallucination (need 3+)."""
        result = _filter_hallucinations(segs("A", "A"))
        assert texts(result) == ["A", "A"]

    def test_all_unique(self):
        result = _filter_hallucinations(segs("A", "B", "C", "D"))
        assert texts(result) == ["A", "B", "C", "D"]

    def test_non_consecutive_repeats_kept(self):
        """Same text appearing non-consecutively is not filtered."""
        result = _filter_hallucinations(segs("A", "B", "A", "B", "A"))
        assert texts(result) == ["A", "B", "A", "B", "A"]


# ── Hallucination detected ────────────────────────────────────────────────────

class TestHallucinationDetected:
    def test_three_consecutive_removes_third(self):
        result = _filter_hallucinations(segs("A", "A", "A"))
        assert texts(result) == ["A", "A"]

    def test_four_consecutive_removes_last_two(self):
        result = _filter_hallucinations(segs("A", "A", "A", "A"))
        assert texts(result) == ["A", "A"]

    def test_five_consecutive_removes_last_three(self):
        result = _filter_hallucinations(segs("A", "A", "A", "A", "A"))
        assert texts(result) == ["A", "A"]

    def test_hallucination_in_middle(self):
        """Loop in the middle: surrounding distinct segments are kept."""
        result = _filter_hallucinations(segs("A", "B", "B", "B", "C"))
        assert texts(result) == ["A", "B", "B", "C"]

    def test_hallucination_at_end(self):
        result = _filter_hallucinations(segs("A", "B", "C", "C", "C"))
        assert texts(result) == ["A", "B", "C", "C"]

    def test_hallucination_at_start(self):
        result = _filter_hallucinations(segs("X", "X", "X", "Y"))
        assert texts(result) == ["X", "X", "Y"]

    def test_two_separate_hallucination_runs(self):
        result = _filter_hallucinations(segs("A", "A", "A", "B", "B", "B"))
        assert texts(result) == ["A", "A", "B", "B"]

    def test_realistic_whisper_loop(self):
        """Whisper repeating a common phrase like [Music] many times."""
        result = _filter_hallucinations(segs(
            "Goede morgen.",
            "[Muziek]", "[Muziek]", "[Muziek]", "[Muziek]", "[Muziek]",
            "Kunt u uw naam geven?",
        ))
        assert texts(result) == ["Goede morgen.", "[Muziek]", "[Muziek]", "Kunt u uw naam geven?"]

    def test_segment_fields_preserved(self):
        """Non-text fields (start, end, speaker, language) are unchanged on kept segments."""
        segments = [
            make_seg("SPK_A", "Zin.", 1.0, 2.0, language="fa"),
            make_seg("SPK_A", "Zin.", 2.1, 3.0, language="fa"),
            make_seg("SPK_A", "Zin.", 3.1, 4.0, language="fa"),  # filtered
            make_seg("SPK_A", "Andere zin.", 4.1, 5.0, language="nl"),
        ]
        result = _filter_hallucinations(segments)
        assert len(result) == 3
        assert result[0]["start"] == 1.0
        assert result[1]["start"] == 2.1
        assert result[2]["text"] == "Andere zin."
        assert result[2]["language"] == "nl"
