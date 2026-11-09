"""Removing invented segments, restoring the first turn, repairing a third language."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import torch

from app.pipeline import _clean_turn_segments, _expected_interpreter_language, _repair_interpreter_languages
from app.services.diarization import _remove_lead_in


def seg(start, end, no_speech=0.1, text="tekst", speaker="T", language="nl"):
    return {"start": start, "end": end, "no_speech_prob": no_speech, "text": text,
            "speaker": speaker, "language": language}


class TestCleanTurnSegments:
    def test_invented_30_second_segment_is_dropped(self):
        assert _clean_turn_segments([seg(0.0, 29.98, no_speech=0.9)], 0.05) == []

    def test_real_text_overrunning_the_turn_is_kept_and_clamped(self):
        kept = _clean_turn_segments([seg(0.0, 3.92, no_speech=0.22)], 2.13)
        assert len(kept) == 1 and kept[0]["end"] == 2.13

    def test_high_no_speech_inside_the_turn_is_kept(self):
        assert len(_clean_turn_segments([seg(0.0, 1.0, no_speech=0.9)], 1.0)) == 1

    def test_small_overrun_is_only_clamped(self):
        kept = _clean_turn_segments([seg(0.0, 2.3, no_speech=0.9)], 2.0)
        assert len(kept) == 1 and kept[0]["end"] == 2.0

    def test_missing_no_speech_counts_as_speech(self):
        item = seg(0.0, 30.0)
        item["no_speech_prob"] = None
        assert len(_clean_turn_segments([item], 1.0)) == 1

    def test_start_never_passes_the_clamped_end(self):
        kept = _clean_turn_segments([seg(3.0, 3.2)], 2.0)
        assert kept[0]["start"] == kept[0]["end"] == 2.0


class TestRemoveLeadIn:
    def test_shifts_back(self):
        out = _remove_lead_in([{"start": 3.0, "end": 5.0, "speaker": "A"}], 2.0)
        assert out == [{"start": 1.0, "end": 3.0, "speaker": "A"}]

    def test_clamps_to_zero(self):
        assert _remove_lead_in([{"start": 1.99, "end": 4.0, "speaker": "A"}], 2.0)[0]["start"] == 0.0

    def test_drops_turns_inside_the_lead_in(self):
        assert _remove_lead_in([{"start": 0.5, "end": 1.5, "speaker": "A"}], 2.0) == []


class TestExpectedLanguage:
    def transcript(self):
        return [seg(0, 1, speaker="O"), seg(1, 2, speaker="T"), seg(2, 3, speaker="C"), seg(3, 4, speaker="T")]

    def test_after_client_is_dutch(self):
        assert _expected_interpreter_language(self.transcript(), 3, "T", "C", "tr") == "nl"

    def test_after_officer_is_client_language(self):
        assert _expected_interpreter_language(self.transcript(), 1, "T", "C", "tr") == "tr"

    def test_nobody_before_gives_none(self):
        assert _expected_interpreter_language([seg(0, 1)], 0, "T", "C", "tr") is None


@pytest.mark.asyncio
class TestRepairInterpreterLanguages:
    async def repair(self, transcript, returned):
        with patch("torchaudio.load", return_value=(torch.zeros(1, 16000 * 60), 16000)), \
                patch("app.services.transcription.transcribe_chunk", AsyncMock(return_value=returned)) as mock:
            out, fixed = await _repair_interpreter_languages(Path("x.wav"), transcript, "T", "C", "tr", None)
        return out, fixed, mock

    async def test_no_third_language_does_not_load_audio(self):
        transcript = [seg(0, 1, speaker="C", language="tr"), seg(1, 2)]
        with patch("torchaudio.load") as load:
            out, fixed = await _repair_interpreter_languages(Path("x.wav"), transcript, "T", "C", "tr", None)
        load.assert_not_called()
        assert out == transcript and fixed == 0

    async def test_one_run_is_retranscribed_in_the_protocol_language(self):
        transcript = [seg(0, 5, speaker="C", language="tr"), seg(5, 7, language="fa"), seg(7, 9, language="fa"),
                      seg(10, 11, speaker="O")]
        out, fixed, mock = await self.repair(transcript, [seg(0.0, 4.0, text="goed")])
        assert fixed == 1 and [s["speaker"] for s in out] == ["C", "T", "O"]
        assert mock.await_args.args[2] == "nl"
        repaired = out[1]
        assert (repaired["start"], repaired["end"]) == (5.0, 9.0)
        assert repaired["language_repaired_from"] == "fa"

    async def test_after_officer_forces_client_language(self):
        transcript = [seg(0, 5, speaker="O"), seg(5, 7, language="en")]
        _, _, mock = await self.repair(transcript, [seg(0.0, 1.0, language="tr")])
        assert mock.await_args.args[2] == "tr"

    async def test_empty_result_keeps_the_original(self):
        transcript = [seg(0, 5, speaker="C", language="tr"), seg(5, 7, language="fa")]
        out, fixed, _ = await self.repair(transcript, [])
        assert fixed == 0 and out == transcript

    async def test_other_speakers_third_language_is_left_alone(self):
        transcript = [seg(0, 5, speaker="C", language="en"), seg(5, 7)]
        out, fixed, mock = await self.repair(transcript, [])
        assert fixed == 0 and out == transcript
        mock.assert_not_awaited()
