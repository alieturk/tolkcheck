"""Unit tests for pipeline._remap_compact_segment.

Phase B re-transcribes the client with a forced language by concatenating that
speaker's audio chunks into one compact waveform (better decode than isolated
short clips), then mapping the resulting timestamps back to original time.

Whisper re-segments the compact audio on its own boundaries, which do not line
up with the chunk boundaries. The mapping therefore has to cope with segments
that straddle chunks, sit in the inter-chunk gap, or extend past the end — and
must never let a remapped client segment land on another speaker's turn.

Pure function: no DB, no models, no audio.
"""
from __future__ import annotations

from app.pipeline import _remap_compact_segment

# Three 10s client turns taken from 0s, 100s and 200s in the original recording,
# concatenated with a 0.1s gap between them:
#
#   compact   0–10      10.1–20.1   20.2–30.2
#   original  0–10     100–110     200–210
SPANS = [
    (0.0,  10.0, 0.0,   10.0),
    (10.1, 20.1, 100.0, 110.0),
    (20.2, 30.2, 200.0, 210.0),
]


def remap(start: float, end: float, spans=SPANS) -> tuple[float, float]:
    seg = {"start": start, "end": end, "text": "x"}
    _remap_compact_segment(seg, spans)
    return round(seg["start"], 3), round(seg["end"], 3)


class TestWithinOneChunk:
    def test_first_chunk_is_unshifted(self):
        assert remap(2.0, 5.0) == (2.0, 5.0)

    def test_second_chunk_shifts_to_its_original_offset(self):
        # 1.9s into chunk 2 → 101.9s in the original
        assert remap(12.0, 15.0) == (101.9, 104.9)

    def test_third_chunk_shifts_to_its_original_offset(self):
        assert remap(21.2, 25.2) == (201.0, 205.0)

    def test_duration_is_preserved(self):
        start, end = remap(11.0, 17.5)
        assert round(end - start, 3) == 6.5


class TestStraddlingChunks:
    def test_attributed_to_the_chunk_it_overlaps_most(self):
        # 9.5–13.0 in compact: 0.5s in chunk 1, 2.9s in chunk 2 → chunk 2 wins
        start, _end = remap(9.5, 13.0)
        assert 100.0 <= start <= 110.0

    def test_clamped_into_the_winning_chunk(self):
        """The whole point: a straddling segment must not keep its compact-space
        duration and run past the end of the turn it was attributed to."""
        start, end = remap(9.5, 13.0)
        assert (start, end) == (100.0, 102.9)

    def test_cannot_extend_beyond_the_chunk_end(self):
        # 19.0–26.0 straddles chunk 2 (1.1s of overlap) and chunk 3 (5.8s), so
        # chunk 3 wins and the result is clamped into chunk 3's original span —
        # it does not keep its 7s compact duration and spill past 210s.
        start, end = remap(19.0, 26.0)
        assert (start, end) == (200.0, 205.8)

    def test_never_lands_on_a_neighbouring_turn(self):
        """Regression: the old mapping shifted by the first-overlapping chunk's
        offset without bounding the result, so a long segment could cover time
        belonging to the officer or interpreter."""
        for start, end in [(9.0, 12.0), (19.5, 22.0), (5.0, 25.0), (0.0, 30.2)]:
            s, e = remap(start, end)
            assert any(o0 <= s <= e <= o1 for _c0, _c1, o0, o1 in SPANS), (start, end, s, e)


class TestEdgeCases:
    def test_segment_inside_the_gap_falls_back_to_nearest_chunk(self):
        # 10.02–10.08 sits entirely in the 0.1s gap between chunk 1 and chunk 2
        start, end = remap(10.02, 10.08)
        assert start <= end
        assert any(o0 <= start <= o1 for _c0, _c1, o0, o1 in SPANS)

    def test_empty_spans_leaves_the_segment_untouched(self):
        assert remap(3.0, 7.0, spans=[]) == (3.0, 7.0)

    def test_single_chunk(self):
        assert remap(1.0, 4.0, spans=[(0.0, 10.0, 50.0, 60.0)]) == (51.0, 54.0)

    def test_start_never_exceeds_end(self):
        for start, end in [(0.0, 0.0), (29.0, 35.0), (10.05, 10.05), (30.0, 30.2)]:
            s, e = remap(start, end)
            assert s <= e, (start, end, s, e)

    def test_result_stays_inside_the_original_recording_timeline(self):
        for start, end in [(0.0, 1.0), (15.0, 16.0), (29.0, 30.2)]:
            s, e = remap(start, end)
            assert 0.0 <= s <= 210.0 and 0.0 <= e <= 210.0
