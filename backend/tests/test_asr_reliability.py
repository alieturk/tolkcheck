"""Tests for the ASR-reliability gate.

Whisper's own decode metrics are the only evidence the pipeline has for telling
"the interpreter said something wrong" apart from "the decoder produced
nonsense". Without the gate a hallucinated block is scored and reported as an
interpreting error — on a hearing transcript that is a finding against a named
professional, so the distinction has to hold.

Covers alignment._block_asr (per-block aggregation) and
pipeline._pair_unassessable (how a flagged block invalidates a pair).
"""
from __future__ import annotations

from app.pipeline import _pair_unassessable
from app.services import alignment
from app.services.alignment import build_blocks
from tests.conftest import make_seg

CLIENT, INTERP, OFFICER = "SPEAKER_00", "SPEAKER_01", "SPEAKER_02"


def blocks_for(*segs):
    return build_blocks(list(segs), interpreter_speaker=INTERP, client_speaker=CLIENT)


class TestBlockAsr:
    def test_healthy_segment_is_reliable(self):
        b = blocks_for(make_seg(CLIENT, "Duidelijke spraak.", 0, 5))[0]
        assert b["asr"]["unreliable"] is False
        assert b["asr"]["reasons"] == []

    def test_low_logprob_flags_the_block(self):
        """Whisper's own logprob_threshold is -1.0; past it the decoder itself
        considers the segment a failed decode."""
        b = blocks_for(make_seg(INTERP, "Erveys inaarefbeidehevaadah.", 0, 3,
                                avg_logprob=-1.6))[0]
        assert b["asr"]["unreliable"] is True
        assert "low_logprob" in b["asr"]["reasons"]

    def test_high_compression_ratio_flags_repetition(self):
        b = blocks_for(make_seg(INTERP, "Hij zegt dat. Hij zegt dat. Hij zegt dat.", 0, 5,
                                compression_ratio=3.1))[0]
        assert "repetitive" in b["asr"]["reasons"]

    def test_high_no_speech_prob_flags_text_over_silence(self):
        """The 'Subtitles by the Amara.org community' class of hallucination."""
        b = blocks_for(make_seg(OFFICER, "Subtitles by the Amara.org community", 0, 0.4,
                                no_speech_prob=0.93))[0]
        assert "no_speech" in b["asr"]["reasons"]

    def test_reasons_accumulate(self):
        b = blocks_for(make_seg(INTERP, "???", 0, 2, avg_logprob=-2.0,
                                compression_ratio=4.0, no_speech_prob=0.9))[0]
        assert set(b["asr"]["reasons"]) == {"low_logprob", "repetitive", "no_speech"}

    def test_worst_case_not_average_across_a_block(self):
        """One bad segment must not be averaged away by good neighbours — the
        block's text is untrustworthy as a whole once any part of it is."""
        b = blocks_for(
            make_seg(INTERP, "Prima zin.", 0, 4, avg_logprob=-0.1),
            make_seg(INTERP, "Gibberish.", 5, 8, avg_logprob=-2.4),
        )[0]
        assert len(b["segments"]) == 2
        assert b["asr"]["min_avg_logprob"] == -2.4
        assert b["asr"]["unreliable"] is True

    def test_missing_metrics_are_not_treated_as_failures(self):
        """Older transcripts predate these fields; absent evidence is not evidence
        of a bad decode."""
        seg = make_seg(CLIENT, "Oude opname.", 0, 5,
                       avg_logprob=None, compression_ratio=None, no_speech_prob=None)
        b = blocks_for(seg)[0]
        assert b["asr"]["unreliable"] is False
        assert b["asr"]["min_avg_logprob"] is None

    def test_thresholds_are_inclusive_boundaries(self):
        at_floor = blocks_for(make_seg(INTERP, "x", 0, 2,
                                       avg_logprob=alignment.LOGPROB_FLOOR))[0]
        assert at_floor["asr"]["unreliable"] is False
        below = blocks_for(make_seg(INTERP, "x", 0, 2,
                                    avg_logprob=alignment.LOGPROB_FLOOR - 0.01))[0]
        assert below["asr"]["unreliable"] is True


class TestPairUnassessable:
    def _pair(self, interp_bad=False, source_bad=False):
        interp = blocks_for(make_seg(INTERP, "vertaling", 0, 3,
                                     avg_logprob=-2.0 if interp_bad else -0.2))[0]
        source = blocks_for(make_seg(CLIENT, "bron", 0, 3,
                                     avg_logprob=-2.0 if source_bad else -0.2))[0]
        return {"interp_block": interp, "source_block": source}

    def test_clean_pair_is_assessable(self):
        assert _pair_unassessable(self._pair()) is False

    def test_bad_interpreter_block_invalidates_the_pair(self):
        assert _pair_unassessable(self._pair(interp_bad=True)) is True

    def test_bad_source_block_invalidates_the_pair(self):
        """Nothing valid to judge the interpreter against."""
        assert _pair_unassessable(self._pair(source_bad=True)) is True

    def test_pair_without_asr_data_is_assessable(self):
        pair = {"interp_block": {"text": "a"}, "source_block": {"text": "b"}}
        assert _pair_unassessable(pair) is False
